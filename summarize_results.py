from __future__ import print_function
"""
outputs to produce for RIST workbook:

- an asset is a zone-technology-vintage combination
x capital outlay for new/replacement assets each period (per asset)
- annual amortization for each asset during each period
- annual O&M per asset per year
- annual fuel cost per asset per year
- maybe group the above into
    - PPA projects (report amortization + fuel + O&M together)
    - HECO-owned (report capital outlay, O&M, fuel)
- annual values:
    - Net Load (GWh)
    - battery/transmission losses (GWh)
    - Customer Count (?) (if have time)
    - Average Residential Use (kWh/month) (?) (if have time)
    - CO2 Emissions (tons)
    - Utility-scale Renewable Generation (GWh)
    - Distributed Generation (GWh)
    - Distributed Generation Capacity (MW)

what is new capacity and those costs (any new, PPA or heco-owned; for now we assume all done through PPA)
when does heco's capacity shutdown?
amortization of capital with 6% plus O&M and fuel

if peopel want to use this scneario as our own, we should lay out our assumptions:
    capacity, shutdown date or start date for these facilities, what capacity was available what year.

net load is net of DG and losses

non-retired thermal should be shown as online even if not used

ASAP (not necessarily this week but she'll be in germany next week)
"""

"""
Look at formulas for these:
['TotalGenFixedCosts',
 'FuelCostsPerPeriod',
 'StorageEnergyInstallCosts',
 'RFM_Fixed_Costs_Annual',
 'Pumped_Hydro_Fixed_Cost_Annual',
 'Federal_Investment_Tax_Credit_Annual']

 ['GenVariableOMCostsInTP', 'Total_StartupGenCapacity_OM_Costs']

Break down by project and sum back up, without discounting.
Also split fixed costs into amortization and O&M.
Then aggregate projects in groups:
HECO-owned (existing thermal except H-POWER, AES, Kalaeloa, cogen; any renewables?)
PPA (H-POWER, AES, Kalaeloa, cogen, most/all renewables?)
Fuel costs: allocate supply curve proportionately based on % fuel used by each plant, i.e., calculate an average cost per MMBtu used and allocate back

** see code for gen_cap.csv
for each project, each period, report
    - capital outlay (power + energy) net of investment tax credits
    - amortization net of investment tax credits
    - fixed O&M
    - variable O&M
    - startup costs
    - fuel expenditure (for markets, use avg. cost in fuel market incl. FuelCostsPerPeriod and RFM_Fixed_Costs_Annual)
    - production (MWh)
    - capacity added (MW)
    - capacity retired (MW)
    - capacity in place
Then also report other cost terms, summed for period:
    - Pumped_Hydro_Fixed_Cost_Annual
    -
Sum and discount to verify that these match objective fn. (also check that amortization matches capital outlays?)

"""

import os, math
import pandas as pd
from collections import OrderedDict, defaultdict
from pyomo.environ import value
from switch_model.financials import capital_recovery_factor as crf

def post_solve(m, outdir=None):
    """ Calculate detailed costs per generation project per period. """

    if outdir is None:
        outdir = m.options.outputs_dir

    zone_fuel_cost = get_zone_fuel_cost(m)
    has_subsidies = hasattr(m, 'gen_investment_subsidy_fraction')

    gen_data = OrderedDict()
    gen_period_data = OrderedDict()
    gen_vintage_period_data = OrderedDict()
    for g, p in sorted(m.GEN_PERIODS):
        # helper function to calculate annual sums
        def ann(expr):
            try:
                return sum(
                    expr(g, t) * m.tp_weight_in_year[t]
                    for t in m.TPS_IN_PERIOD[p]
                )
            except AttributeError:
                # expression uses a component that doesn't exist
                return None

        # is this a storage gen?
        is_storage = hasattr(m, 'STORAGE_GENS') and g in m.STORAGE_GENS

        BuildGen = m.BuildGen[g, p] if (g, p) in m.GEN_BLD_YRS else 0.0
        # BuildStorageEnergy = (
        #     m.BuildStorageEnergy[g, p]
        #     if is_storage and (g, p) in m.GEN_BLD_YRS
        #     else 0.0
        # )

        gen_data[g] = OrderedDict(
            gen_tech=m.gen_tech[g],
            gen_load_zone=m.gen_load_zone[g],
            gen_energy_source=m.gen_energy_source[g],
            gen_is_intermittent=int(m.gen_is_variable[g])
        )

        # temporary storage of per-generator data to be allocated per-vintage
        # below
        gen_period_data = OrderedDict(
            total_output=0.0 if is_storage else ann(
                lambda g, t: m.DispatchGen[g, t]
            ),
            renewable_output=0.0 if is_storage else ann(
                lambda g, t: renewable_mw(m, g, t)
            ),
            non_renewable_output=0.0 if is_storage else ann(
                lambda g, t: m.DispatchGen[g, t]-renewable_mw(m, g, t)
            ),
            storage_load=(
                ann(lambda g, t: m.ChargeStorage[g, t] - m.DispatchGen[g, t])
                if is_storage else 0.0
            ),
            fixed_om=m.GenFixedOMCosts[g, p],
            variable_om=ann(
                lambda g, t: m.DispatchGen[g, t] * m.gen_variable_om[g]
            ),
            startup_om=ann(
                lambda g, t:
                m.gen_startup_om[g]
                * m.StartupGenCapacity[g, t] / m.tp_duration_hrs[t]
            ),
            fuel_cost=ann(
                lambda g, t: sum(
                    0.0     # avoid nan fuel prices for unused fuels
                    if (
                        abs(value(m.GenFuelUseRate[g, t, f])) < 1e-10
                        and math.isnan(zone_fuel_cost[m.gen_load_zone[g], f, m.tp_period[t]])
                    ) else (
                        m.GenFuelUseRate[g, t, f]
                        * zone_fuel_cost[m.gen_load_zone[g], f, m.tp_period[t]]
                    )
                    for f in m.FUELS_FOR_GEN[g]
                ) if g in m.FUEL_BASED_GENS else 0.0
            )
        )

        for v in m.BLD_YRS_FOR_GEN_PERIOD[g, p]:
            # fill in data for each vintage of generator that is active now
            gen_vintage_period_data[g, v, p] = OrderedDict(
                capacity_in_place=m.BuildGen[g, v],
                capacity_added=m.BuildGen[g, p] if p == v else 0.0,
                capital_outlay=(
                    m.BuildGen[g, p] * (
                        m.gen_overnight_cost[g, p] +
                        m.gen_connect_cost_per_mw[g]
                    ) * (
                        (1.0 - m.gen_investment_subsidy_fraction[g, p])
                        if has_subsidies else 1.0
                    ) + (
                        (
                            m.BuildStorageEnergy[g, p]
                            * m.gen_storage_energy_overnight_cost[g, p]
                        ) if is_storage else 0.0
                    )
                ) if p == v else 0.0,
                amortized_cost=
                    m.BuildGen[g, v] * m.gen_capital_cost_annual[g, v]
                    + ((
                        m.BuildStorageEnergy[g, v]
                        * m.gen_storage_energy_overnight_cost[g, v]
                        * crf(m.interest_rate, m.gen_max_age[g])
                    ) if is_storage else 0.0)
                    - ((
                        m.gen_investment_subsidy_fraction[g, v]
                        * m.BuildGen[g, v]
                        * m.gen_capital_cost_annual[g, v]
                    ) if has_subsidies else 0.0),
            )
            # allocate per-project values among the vintages based on amount
            # of capacity currently online (may not be physically meaningful if
            # gens have discrete commitment, but we assume the gens are run
            # roughly this way)
            vintage_share = ratio(m.BuildGen[g, v], m.GenCapacity[g, p])
            for var, val in gen_period_data.items():
                gen_vintage_period_data[g, v, p][var] = vintage_share * val

    # record capacity retirements
    # (this could be done earlier if we included the variable name
    # in the dictionary key tuple instead of having a data dict for
    # each key)
    for g, v in m.GEN_BLD_YRS:
        retire_year = v + m.gen_max_age[g]
        # find the period when this retires
        for p in m.PERIODS:
            if p >= retire_year:
                gen_vintage_period_data \
                    .setdefault((g, v, p), OrderedDict())['capacity_retired'] \
                    = m.BuildGen[g, v]
                break

    # convert dicts to data frames
    generator_df = (
        pd.DataFrame(evaluate(gen_vintage_period_data))
        .unstack()
        .to_frame(name='value')
    )
    generator_df.index.names = [
        'generation_project', 'gen_vintage', 'period', 'variable'
    ]
    for g, d in gen_data.items():
        for k, v in d.items():
            # assign generator general data to all rows with generator==g
            generator_df.loc[g, k] = v
    # convert from float
    generator_df['gen_is_intermittent'] = generator_df['gen_is_intermittent'].astype(int)
    generator_df = generator_df.reset_index().set_index([
        'generation_project', 'gen_vintage', 'gen_tech', 'gen_load_zone',
        'gen_energy_source', 'gen_is_intermittent',
        'variable'
    ]).sort_index()
    generator_df.to_csv(
        os.path.join(outdir, 'generation_project_details.csv'), index=True
    )

    # dict should be var, gen, period
    # but gens have all-years values too (technology, fuel, etc.)
    # and there are per-year non-gen values

    # report other costs on an undiscounted, annualized basis
    # (custom modules, transmission, etc.)

    # List of comparisons to make later; dict value shows which model
    # components should match which variables in generator_df
    itemized_cost_comparisons = {
        'gen_fixed_cost': (
            [
                'TotalGenFixedCosts', 'StorageEnergyFixedCost',
                'TotalGenCapitalCostsSubsidy'
            ],
            ['amortized_cost', 'fixed_om']
        ),
        'fuel_cost': (
            ['FuelCostsPerPeriod', 'RFM_Fixed_Costs_Annual'],
            ['fuel_cost']
        ),
        'variable_om': (
            ['GenVariableOMCostsInTP', 'Total_StartupGenCapacity_OM_Costs'],
            ['startup_om', 'variable_om']
        )
    }

    ##### most detailed level of data:
    # owner, tech, generator, fuel (if relevant, otherwise 'all' or specific fuel or 'multiple'?)
    # then aggregate up
    """
    In generic summarize_results.py:
    - lists of summary expressions; each creates a new variable per indexing set
      then those get added to summary tables, which then get aggregated
    gen_fuel_period_exprs
    gen_period_exprs (can incl. owner, added to top of list from outside)
    gen_exprs -> get pushed down into gen_period table? or only when creating by-period summaries?
    period_exprs (get added as quasi-gens)
    fuel_period_exprs

    these create tables like 'summary_per_gen_fuel_period' (including quasi gen
    data from period_exprs and fuel_period_exprs).
    Those get pivoted
    to make 'summary_per_gen_fuel_by_period', with data from 'summary_per_gen_fuel'
    added to the same rows. Maybe there should be a list of summary groups too. ugh.
    """




    # list of costs that should have already been accounted for
    itemized_gen_costs = set(
        component
        for model_costs, df_costs in itemized_cost_comparisons.values()
        for component in model_costs
    )

    non_gen_costs = OrderedDict()
    for p in m.PERIODS:
        non_gen_costs[p] = {
            cost: getattr(m, cost)[p]
            for cost in m.Cost_Components_Per_Period
            if cost not in itemized_gen_costs
        }
        for cost in m.Cost_Components_Per_TP:
            if cost not in itemized_gen_costs:
                non_gen_costs[p][cost] = sum(
                    getattr(m, cost)[t] * m.tp_weight_in_year[t]
                    for t in m.TPS_IN_PERIOD[p]
                )
        non_gen_costs[p]['co2_emissions'] = m.AnnualEmissions[p]
        non_gen_costs[p]['gross_load'] = ann(
            lambda g, t: sum(m.zone_demand_mw[z, t] for z in m.LOAD_ZONES)
        )
        non_gen_costs[p]['ev_load'] = 0.0
        if hasattr(m, 'ChargeEVs'):
            non_gen_costs[p]['ev_load'] += ann(
                lambda g, t: sum(m.ChargeEVs[z, t] for z in m.LOAD_ZONES)
            )
        if hasattr(m, 'ev_charge_min') and hasattr(m, 'ChargeEVs_min'):
            m.logger.error(
                'ERROR: Need to update {} to handle combined loads from '
                'ev_simple and ev_advanced modules'.format(__name__)
            )
        if hasattr(m, 'StorePumpedHydro'):
            non_gen_costs[p]['Pumped_Hydro_Net_Load'] = ann(
                lambda g, t: sum(
                    m.StorePumpedHydro[z, t] - m.GeneratePumpedHydro[z, t]
                    for z in m.LOAD_ZONES
                )
            )

    non_gen_df = pd.DataFrame(evaluate(non_gen_costs)).unstack().to_frame(name='value')
    non_gen_df.index.names=['period', 'variable']
    non_gen_df.to_csv(os.path.join(outdir, 'non_generation_costs_by_period.csv'))

    # check whether reported generator costs match values used in the model
    gen_df_totals = generator_df.groupby(['variable', 'period'])['value'].sum()
    gen_total_costs = defaultdict(float)
    for label, (model_costs, df_costs) in itemized_cost_comparisons.items():
        for p in m.PERIODS:
            for cost in model_costs:
                if cost in m.Cost_Components_Per_Period:
                    cost_val = value(getattr(m, cost)[p])
                elif cost in m.Cost_Components_Per_TP:
                    # aggregate to period
                    cost_val = value(sum(
                        getattr(m, cost)[t] * m.tp_weight_in_year[t]
                        for t in m.TPS_IN_PERIOD[p]
                    ))
                else:
                    cost_val = 0.0
                gen_total_costs[label, p, 'model'] += cost_val
            gen_total_costs[label, p, 'reported'] = (
                gen_df_totals.loc[df_costs, p].sum()
            )
            mc = gen_total_costs[label, p, 'model']
            rc = gen_total_costs[label, p, 'reported']
            if different(mc, rc):
                m.logger.warning(
                    "WARNING: model values ({}) don't match reported values ({}) for {} in "
                    "{}: {:,.0f} != {:,.0f}; NPV of difference: {:,.0f}."
                    .format(
                        '+'.join(model_costs), '+'.join(df_costs),
                        label, p, mc, rc,
                        m.bring_annual_costs_to_base_year[p]*(mc-rc)
                    )
                )
                breakpoint()
            # else:
            #     m.logger.info(
            #         "INFO: model and reported values match for {} in "
            #         "{}: {} == {}.".format(label, p, mc, rc)
            #     )

    # check costs on an aggregated basis too (should be OK if the gen costs are)
    cost_vars = [
        var
        for model_costs, df_costs in itemized_cost_comparisons.values()
        for var in df_costs
    ]
    total_costs = (
        generator_df.loc[pd.IndexSlice[:, :, :, :, cost_vars], :]
        .groupby('period')['value'].sum()
    ) + non_gen_df.unstack(0).drop(
        ['co2_emissions', 'gross_load', 'Pumped_Hydro_Net_Load']
    ).sum()
    npv_cost = value(sum(
        m.bring_annual_costs_to_base_year[p] * v
        for ((_, p), v) in total_costs.iteritems()
    ))
    system_cost = value(m.SystemCost)
    if different(npv_cost, system_cost):
        m.logger.warning(
            "WARNING: NPV of all costs in model doesn't match reported total: "
            "{:,.0f} != {:,.0f}; difference: {:,.0f}."
            .format(npv_cost, system_cost, npv_cost - system_cost)
        )


    print()
    print("TODO: *** check for missing MWh terms in {}.".format(__name__))
    print()

    print("Creating RIST summary; may take several minutes.")
    summarize_for_rist(m, outdir)

    # data for HECO info request 2/14/20
    print("Saving hourly reserve data.")
    report_hourly_reserves(m)
    if hasattr(m, 'Smooth_Free_Variables'):
        # using the smooth_dispatch module; re-report dispatch data
        print("Re-saving dispatch data after smoothing.")
        import switch_model.generators.core.dispatch as dispatch
        dispatch.post_solve(m, m.options.outputs_dir)
    else:
        print(
            "WARNING: the smooth_dispatch module is not being used. Hourly "
            "dispatch may be rough and hourly contingency reserve targets may "
            "inflated."
        )

    print("Comparing Switch to EIA production data.")
    if True:
        compare_switch_to_eia_production(m)
    else:
        print("(skipped, takes several minutes)")

    # value(m.SystemCost) ==
    # import code
    # code.interact(local=dict(list(globals().items()) + list(locals().items())))

def different(v1, v2):
    """ True if v1 and v2 differ by more than 0.000001 * their average value """
    return abs(v1 - v2) > 0.0000005 * (v1 + v2)

def renewable_mw(m, g, t):
    if not hasattr(m, "RPS_ENERGY_SOURCES"):
        return 0.0
    elif m.gen_energy_source[g] in m.RPS_ENERGY_SOURCES:
        return m.DispatchGen[g, t]
    elif g in m.FUEL_BASED_GENS:
        return m.DispatchGenRenewableMW[g, t]
    else:
        return 0.0


def ratio(x, y):
    """ Return ratio of x/y, giving 0 if x is 0, even if y is 0 """
    return 0.0 if abs(value(x)) < 1e-9 and abs(value(y)) < 1e-9 else value(x / y)

def evaluate(d):
    return {
        k1: {
            k2: value(v2)
            for k2, v2 in v1.items()
        }
        for k1, v1 in d.items()
    }

def get_zone_fuel_cost(m):
    """
    Calculate average cost of each fuel in each load zone during each period
    """
    if hasattr(m, 'REGIONAL_FUEL_MARKETS'):
        # using fuel markets
        # note: we fuel market expansion because that may be treated as a
        # capital expense or may be factored into the fuel cost
        rfm_fuel_expend = {
            (rfm, p):
            sum(
                m.ConsumeFuelTier[rfm_st] * m.rfm_supply_tier_cost[rfm_st]
                for rfm_st in m.SUPPLY_TIERS_FOR_RFM_PERIOD[rfm, p]
            )
            for rfm in m.REGIONAL_FUEL_MARKETS for p in m.PERIODS
        }
        rfm_fuel_use = {
            (rfm, p):
            sum(
                m.ConsumeFuelTier[rfm_st]
                for rfm_st in m.SUPPLY_TIERS_FOR_RFM_PERIOD[rfm, p]
            )
            for rfm in m.REGIONAL_FUEL_MARKETS for p in m.PERIODS
        }
        rfm_fuel_cost = {
            (rfm, p):
            float('nan') if rfm_fuel_use[rfm, p] == 0.0 else
            (rfm_fuel_expend[rfm, p] / rfm_fuel_use[rfm, p])
            for rfm in m.REGIONAL_FUEL_MARKETS for p in m.PERIODS
        }
        # assign to corresponding zones and fuels
        zone_fuel_cost = {
            (z, f, p): rfm_fuel_cost[m.zone_fuel_rfm[z, f], p]
            for z, f in m.ZONE_FUELS
            for p in m.PERIODS
        }
    else:
        # simple fuel costs
        zone_fuel_cost = {(z, f, p): m.fuel_cost[z, f, p]}

    # convert to floats to view and evaluate more easily (e.g., apply isnan)
    zone_fuel_cost = {k: value(v) for k, v in zone_fuel_cost.items()}

    return zone_fuel_cost

    # outdir='outputs'
    # summarize_for_rist(m, outdir)
def summarize_for_rist(m, outdir=''):
    non_gen_df = pd.read_csv(
        os.path.join(outdir, 'non_generation_costs_by_period.csv')
    ).set_index(['variable', 'period'])['value'].unstack()
    gen_df = pd.read_csv(
        os.path.join(outdir, 'generation_project_details.csv')
    )
    techs_for_owner = dict(
        PPA=['AES', 'Battery_Bulk', 'CC_152', 'CentralTrackingPV',
           'H-Power', 'IC_Barge', 'IC_MCBH',
           'Hawaii_Cogen', 'Tesoro_Hawaii',
           'Kalaeloa_CC1', 'Kalaeloa_CC2', 'Kalaeloa_CC3',
           'OffshoreWind', 'OnshoreWind'
        ],
        HECO=[
            'Airport_DSG', 'Battery_Conting', 'Battery_Reg', 'CIP_CT',
            'IC_Schofield',
            'Honolulu_8', 'Honolulu_9',
            'Kahe_1', 'Kahe_2', 'Kahe_3', 'Kahe_4', 'Kahe_5', 'Kahe_6',
            'Waiau_3', 'Waiau_4', 'Waiau_5', 'Waiau_6', 'Waiau_7', 'Waiau_8',
            'Waiau_9', 'Waiau_10',
        ],
        distributed=['DistBattery', 'FlatDistPV', 'SlopedDistPV']
    )
    owner_for_tech = {t: o for o, techs in techs_for_owner.items() for t in techs}
    gen_df['owner'] = gen_df['gen_tech'].replace(owner_for_tech)
    missing_owners = set(gen_df['owner']) - set(techs_for_owner.keys())
    if missing_owners:
        print("\nWARNING: some plants were not assigned owners: {}\n".format(missing_owners))
    gen_cols = ['owner', 'variable', 'gen_tech', 'gen_vintage', 'gen_is_intermittent', 'period']
    gen_df = gen_df.groupby(gen_cols)['value'].sum().unstack()
    gen_df.loc[('PPA', 'ppa_cost', 'PumpedHydro', '', 0), :] \
        = non_gen_df.loc['Pumped_Hydro_Fixed_Cost_Annual', :]
    gen_df.loc[('PPA', 'storage_net_load', 'PumpedHydro', '', 0), :] \
        = non_gen_df.loc['Pumped_Hydro_Net_Load', :]
    for col in ['co2_emissions', 'gross_load', 'ev_load']:
        gen_df.loc[('system', col, '', '', ''), :] = non_gen_df.loc[col, :]

    gen_df = gen_df.reindex(range(min(gen_df.columns), 2050), axis=1)
    gen_df.update(gen_df.loc[pd.IndexSlice[:, ['capacity_added', 'capacity_retired', 'capital_outlay'], :], :].fillna(0))
    # carry other values forward to the end of the period
    period_edges = non_gen_df.columns.to_list() + [2050]
    for start, end in zip(period_edges[:-1], period_edges[1:]):
        gen_df.update(
            gen_df.loc[:, start:end-1].fillna(method='ffill', axis=1)
        )
    gen_df = gen_df.sort_index()
    # drop zeros and then drop all-nan rows
    print("TODO: report 0 production until end-of-life for generators, so it's easier to see idle capacity")
    gen_df = gen_df.replace(0, float('nan')).dropna(how='all')
    gen_df.to_csv(os.path.join(outdir, 'annual_details_by_tech.csv'))

    var_df = gen_df.groupby(['owner', 'variable']).sum()
    var_df.to_csv(os.path.join(outdir, 'annual_details_by_owner.csv'))


def compare_switch_to_eia_production(m):
    # get totals per gen, aggregate up to group level (can probably just select by matching project name)

    switch_data = dict()

    def vsum(iter):
        return value(sum(iter))

    for g, p in m.GEN_PERIODS:
        dispatch = (
            (lambda m, g, t: m.DispatchGen[g, t] - m.ChargeStorage[g, t])
            if g in m.STORAGE_GENS else
            (lambda m, g, t: m.DispatchGen[g, t])
        )
        if g in m.FUEL_BASED_GENS:
            total_fuel_in_tp = {
                t: vsum(m.GenFuelUseRate[g, t, f] for f in m.FUELS_FOR_GEN[g])
                for t in m.TPS_IN_PERIOD[p]
            }
            for f in m.FUELS_FOR_GEN[g]:
                fuel_use = vsum(
                    m.GenFuelUseRate[g, t, f] * m.tp_weight_in_year[t]
                    for t in m.TPS_IN_PERIOD[p]
                )
                if fuel_use != 0.0:
                    switch_data[g, f, p, 'fuel_use'] = fuel_use
                    # prorate production among sources
                    switch_data[g, f, p, 'production'] = vsum(
                        dispatch(m, g, t)
                        * m.tp_weight_in_year[t]
                        * ratio(
                            m.GenFuelUseRate[g, t, f], total_fuel_in_tp[t]
                        )
                        for t in m.TPS_IN_PERIOD[p]
                    )
        else:
            switch_data[g, m.gen_energy_source[g], p, 'fuel_use'] = 0.0
            switch_data[g, m.gen_energy_source[g], p, 'production'] = vsum(
                dispatch(m, g, t) * m.tp_weight_in_year[t]
                for t in m.TPS_IN_PERIOD[p]
            )
    switch_df = pd.Series(switch_data, name='value').to_frame()
    switch_df.index.names=['generation_project', 'switch_fuel', 'year', 'variable']
    switch_df = switch_df.reset_index()
    ### TODO: add lake_wilson

    # Get EIA data

    # list of plants; tends to include some that are retired, so no need to
    # look further back
    # ~5s
    oahu_plants = read_excel_cached(
        os.path.join('EIA data', 'eia8602018', '2___Plant_Y2018.xlsx'),
        sheet_name='Plant',
        skiprows=1,
        header=0, index_col=None
    )
    oahu_plants = oahu_plants.loc[
        (oahu_plants['State']=='HI') & (oahu_plants['County']=='Honolulu'),
        ['Plant Code']
    ].rename({'Plant Code': 'Plant Id'}, axis=1).reset_index(drop=True)

    # get EIA production and fuel data
    # year = 2018
    eia_dfs = []
    for year in range(2012, 2019+1):
        # ~21s
        filename = os.path.join(
            'EIA data',
            'EIA923_Schedules_2_3_4_5_M_12_{}_Final_Revision.xlsx'.format(year)
        )
        if not os.path.exists(filename):
            if year == 2019:
                filename = filename.replace('Final_Revision', '21FEB2020')
            elif year == 2013:
                filename = filename.replace('5_M_12_20', '5_20')

        df = read_excel_cached(
            filename,
            sheet_name='Page 1 Generation and Fuel Data',
            skiprows=5,
            header=0, index_col=None
        )
        df = df.merge(oahu_plants, on='Plant Id', how='inner')
        df.columns = [c.replace('\n', ' ') for c in df.columns]
        df = df.rename({
            'YEAR': 'year',
            'AER Fuel Type Code': 'eia_fuel',
            'Elec Fuel Consumption MMBtu': 'fuel_use',
            'Net Generation (Megawatthours)': 'production'
        }, axis=1)
        df['plant_mover'] = df['Plant Name'] + ' ' + df['Reported Prime Mover']
        df = df.loc[df['production'] != 0.0, :]  # drop extraneous records
        eia_dfs.append(df.melt(
            id_vars=['plant_mover', 'eia_fuel', 'year'],
            value_vars=['production', 'fuel_use'],
            var_name='variable', value_name='value'
        ))
    eia_df = pd.concat(eia_dfs, axis=0)

    # give plants and fuels common names
    eia_plant_name, switch_plant_name = get_eia_switch_plants(eia_df, switch_df)
    eia_fuel_name, switch_fuel_name = get_eia_switch_fuels(eia_df, switch_df)

    eia_df['fuel'] = eia_df['eia_fuel'].replace(eia_fuel_name)
    switch_df['fuel'] = switch_df['switch_fuel'].replace(switch_fuel_name)
    eia_df['plant'] = eia_df['plant_mover'].replace(eia_plant_name)
    switch_df['plant'] = switch_df['generation_project'].replace(switch_plant_name)

    eia_df['source'] = 'actual'
    switch_df['source'] = 'switch'
    cols = ['variable', 'plant', 'fuel', 'source', 'year', 'value']
    compare = (
        pd.concat([eia_df.loc[:, cols], switch_df.loc[:, cols]], axis=0)
        .groupby(cols[:-1])
        .sum()
        .unstack(['source', 'year'])
    ).loc[:, 'value'].sort_index(axis=0).sort_index(axis=1)
    compare.to_csv(os.path.join(m.options.outputs_dir, 'compare_eia_switch_production.csv'))

import hashlib
def read_excel_cached(excel_file, *args, **kwargs):
    h = hashlib.sha1(str([args, kwargs]).encode()).hexdigest()[:6]
    pickle_file = os.path.splitext(excel_file)[0] + '.' + h + '.zip'
    if os.path.exists(pickle_file):
        df = pd.read_pickle(pickle_file)
    else:
        print("Reading {} and caching in {}; takes about 20s.".format(excel_file, pickle_file))
        df = pd.read_excel(excel_file, *args, **kwargs)
        df.to_pickle(pickle_file)
    return df

def get_eia_switch_fuels(eia_df, switch_df):
    # for f in eia_df['fuel'].unique():
    #     print(f"'': (['{f}'], ['']),")
    # for f in switch_df['fuel'].unique():
    #     print(f"'{f}'")
    eia_switch_fuels = {
        'LSFO': (['RFO'], ['LSFO']),
        'diesel': (['DFO'], ['Diesel']),
        'waste oil': (['WOO'], []),
        'gas': (['OOG'], ['LNG']),
        'muni waste': (['MLG'], ['MSW']),
        'other': (['OTH'], ['Battery']),
        'coal': (['COL'], ['Coal']),
        'biodiesel': (['ORW'], ['Biodiesel']),
        'wind': (['WND'], ['WND']),
        'solar': (['SUN'], ['SUN']),
    }
    # add missing EIA fuels
    included_fuels = set(
        f
        for eia_fuels, switch_fuels in eia_switch_fuels.values()
        for f in eia_fuels
    )
    eia_switch_fuels.update({
        f: ([f], [])
        for f in eia_df['eia_fuel'].unique()
        if f not in included_fuels
    })
    # add missing Switch fuels
    included_fuels = set(
        f
        for eia_fuels, switch_fuels in eia_switch_fuels.values()
        for f in switch_fuels
    )
    eia_switch_fuels.update({
        f: ([], [f])
        for f in switch_df['switch_fuel'].unique()
        if f not in included_fuels
    })
    # split into eia conversion table and switch conversion table
    eia_renamer = {
        f: name
        for name, (eia_fuels, switch_fuels) in eia_switch_fuels.items()
        for f in eia_fuels
    }
    switch_renamer = {
        f: name
        for name, (eia_fuels, switch_fuels) in eia_switch_fuels.items()
        for f in switch_fuels
    }
    return eia_renamer, switch_renamer

# print("""
# ========================================
# TODO (fix these problems):
# ========================================
# """)


def get_eia_switch_plants(eia_df, switch_df):
    # get lists of Oahu plants and prime movers (gives initial data for
    # eia_switch_plants dict)
    # {m: (['{}'.format(m)], []) for m in df['plant_mover'].drop_duplicates().sort_values()}
    # list(m.GENERATION_PROJECTS)
    # (also see existing plants spreadsheet in Switch's database inputs)

    # map eia plants to switch projects (many to many)
    eia_switch_plants = {
        'AES Coal': (['AES Hawaii ST'], ['Oahu_AES']),
        'CIP CT': (['Campbell Industrial Park GT'], ['Oahu_CIP_CT']),
        'H-Power': (['H Power ST'], ['Oahu_H-Power']),
        'Airport DSG': (
            ['HNL Emergency Power Facility IC'],
            ['Oahu_Airport_DSG']
        ),
        'Par and Tesoro cogen': (
            ['Hawaii Cogen GT', 'Tesoro Hawaii GT'],
            ['Oahu_Hawaii_Cogen', 'Oahu_Tesoro_Hawaii']
        ),
        'Kahe': (
            ['Kahe ST'],
            [
                'Oahu_Kahe_1',
                'Oahu_Kahe_2',
                'Oahu_Kahe_3',
                'Oahu_Kahe_4',
                'Oahu_Kahe_5',
                'Oahu_Kahe_6',
            ]
        ),
        'Kahuku Wind': (
            ['Kahuku Wind Power LLC WT'],
            ['Oahu_OnshoreWind_OnWind_Kahuku']
        ),
        'Kalaeloa': (
            ['Kalaeloa Cogen Plant CA', 'Kalaeloa Cogen Plant CT'],
            [
                'Oahu_Kalaeloa_CC1',  # train 1
                'Oahu_Kalaeloa_CC2',  # train 2
                'Oahu_Kalaeloa_CC3',  # duct burner
            ]
        ),
        'Kawailoa Wind': (
            ['Kawailoa Wind WT'],
            ['Oahu_OnshoreWind_OnWind_Kawailoa']
        ),
        'Schofield Generating Station IC': (
            ['Schofield Generating Station IC'],
            ['Oahu_IC_Schofield']
        ),
        'Waiau GT': (
            ['Waiau GT'],
            ['Oahu_Waiau_10', 'Oahu_Waiau_9']
        ),
        'Waiau ST': (
            ['Waiau ST'],
            [
                'Oahu_Waiau_3',
                'Oahu_Waiau_4',
                'Oahu_Waiau_5',
                'Oahu_Waiau_6',
                'Oahu_Waiau_7',
                'Oahu_Waiau_8',
            ]
        ),
        'Batteries': (
            ['Campbell Industrial Park BESS BA'],
            [
                'Oahu_Battery_Bulk',
                'Oahu_Battery_Reg',      # should always be 0
                'Oahu_Battery_Conting',  # should always be 0
                'Oahu_DistBattery'
            ]
        ),
        'Utility-Scale Solar': (
            [
                'Aloha Solar Energy Fund 1 PK1 PV',
                'Kalaeloa Solar Two PV',
                'Kalaeloa Renewable Energy Park PV',
                'Kapolei Solar Energy Park PV',
                'Waihonu North Solar PV',
                'Waihonu South Solar PV',
                'Pearl City Peninsula Solar Park PV',
                'EE Waianae Solar Project PV',
                'Kawailoa Solar PV',
                'Waipio Solar PV',
            ],
            [
                'Oahu_CentralTrackingPV_PV_01',
                'Oahu_CentralTrackingPV_PV_02',
                'Oahu_CentralTrackingPV_PV_03',
                'Oahu_CentralTrackingPV_PV_04',
                'Oahu_CentralTrackingPV_PV_05',
                'Oahu_CentralTrackingPV_PV_06',
                'Oahu_CentralTrackingPV_PV_07',
                'Oahu_CentralTrackingPV_PV_08',
                'Oahu_CentralTrackingPV_PV_09',
                'Oahu_CentralTrackingPV_PV_10',
                'Oahu_CentralTrackingPV_PV_11',
                'Oahu_CentralTrackingPV_PV_12',
                'Oahu_CentralTrackingPV_PV_13',
                'Oahu_CentralTrackingPV_PV_14',
                'Oahu_CentralTrackingPV_PV_15',
                'Oahu_CentralTrackingPV_PV_16',
                'Oahu_CentralTrackingPV_PV_17',
                'Oahu_CentralTrackingPV_PV_18',
            ]
        ),
        'New Onshore Wind': (
            [],
            [
                'Oahu_OnshoreWind_OnWind_101',
                'Oahu_OnshoreWind_OnWind_102',
                'Oahu_OnshoreWind_OnWind_103',
                'Oahu_OnshoreWind_OnWind_104',
                'Oahu_OnshoreWind_OnWind_105',
                'Oahu_OnshoreWind_OnWind_106',
                'Oahu_OnshoreWind_OnWind_107',
                'Oahu_OnshoreWind_OnWind_201',
                'Oahu_OnshoreWind_OnWind_202',
                'Oahu_OnshoreWind_OnWind_203',
                'Oahu_OnshoreWind_OnWind_204',
                'Oahu_OnshoreWind_OnWind_205',
                'Oahu_OnshoreWind_OnWind_206',
                'Oahu_OnshoreWind_OnWind_207',
                'Oahu_OnshoreWind_OnWind_208',
                'Oahu_OnshoreWind_OnWind_209',
                'Oahu_OnshoreWind_OnWind_301',
                'Oahu_OnshoreWind_OnWind_302',
                'Oahu_OnshoreWind_OnWind_303',
                'Oahu_OnshoreWind_OnWind_304',
                'Oahu_OnshoreWind_OnWind_305',
                'Oahu_OnshoreWind_OnWind_306',
                'Oahu_OnshoreWind_OnWind_307',
                'Oahu_OnshoreWind_OnWind_308',
                'Oahu_OnshoreWind_OnWind_309',
                'Oahu_OnshoreWind_OnWind_401',
                'Oahu_OnshoreWind_OnWind_402',
                'Oahu_OnshoreWind_OnWind_403',
                'Oahu_OnshoreWind_OnWind_404',
                'Oahu_OnshoreWind_OnWind_405',
                'Oahu_OnshoreWind_OnWind_406',
                'Oahu_OnshoreWind_OnWind_407',
                'Oahu_OnshoreWind_OnWind_408',
                'Oahu_OnshoreWind_OnWind_409',
                'Oahu_OnshoreWind_OnWind_410',
                'Oahu_OnshoreWind_OnWind_501',
                'Oahu_OnshoreWind_OnWind_502',
                'Oahu_OnshoreWind_OnWind_503',
                'Oahu_OnshoreWind_OnWind_504',
                'Oahu_OnshoreWind_OnWind_505',
                'Oahu_OnshoreWind_OnWind_506',
                'Oahu_OnshoreWind_OnWind_507',
                'Oahu_OnshoreWind_OnWind_508',
                'Oahu_OnshoreWind_OnWind_509',
            ]
        ),
        'New Offshore Wind': ([], ['Oahu_OffshoreWind_OffWind']),
        'Distributed PV': (
            [],
            [
                'Oahu_FlatDistPV_Oahu_FlatDistPV_0',
                'Oahu_FlatDistPV_Oahu_FlatDistPV_1',
                'Oahu_FlatDistPV_Oahu_FlatDistPV_2',
                'Oahu_FlatDistPV_Oahu_FlatDistPV_3',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_0',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_1',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_10',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_11',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_12',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_13',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_14',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_15',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_2',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_3',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_4',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_5',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_6',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_7',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_8',
                'Oahu_SlopedDistPV_Oahu_SlopedDistPV_9',
            ]
        ),
        'IC Barge': ([], ['Oahu_IC_Barge']),
        'IC MCBH': ([], ['Oahu_IC_MCBH']),
        'New CC 152': ([], ['Oahu_CC_152'])
    }
    # add missing Switch projects
    included_projects = set(
        g
        for plants, projects in eia_switch_plants.values()
        for g in projects
    )
    eia_switch_plants.update({
        gp: ([], [gp])
        for gp in switch_df['generation_project'].unique()
        if gp not in included_projects
    })
    # add missing EIA plants
    included_plants = set(
        p
        for plants, projects in eia_switch_plants.values()
        for p in plants
    )
    eia_switch_plants.update({
        pm: ([pm], [])
        for pm in eia_df['plant_mover'].unique()
        if pm not in included_plants
    })
    # split into eia conversion table and switch conversion table
    eia_renamer = {
        p: name
        for name, (plants, projects) in eia_switch_plants.items()
        for p in plants
    }
    switch_renamer = {
        p: name
        for name, (plants, projects) in eia_switch_plants.items()
        for p in projects
    }
    return eia_renamer, switch_renamer

def report_hourly_reserves(m):
    import os
    import pandas as pd
    rows = []
    for dir in ['Up', 'Down']:
        cmp = getattr(m, 'Satisfy_Spinning_Reserve_{}_Requirement'.format(dir))
        rows.extend([
            (
                ba, rt, dir.lower(), m.tp_timestamp[tp],
                constr.body.args[0](),
                m.ts_scale_to_year[m.tp_ts[tp]]
            )
            for (rt, ba, tp), constr in cmp.iteritems()
        ])
    reserves = pd.DataFrame(rows, columns=[
        'balancing_area', 'reserve_type', 'direction', 'timepoint',
        'target', 'day_repeat'
    ])
    outfile = os.path.join(m.options.outputs_dir, 'reserve_requirements.csv')
    reserves.to_csv(outfile, index=False)
    print("Created {}".format(outfile))

if __name__ == '__main__' and 'm' not in locals():
    # For debugging:
    import sys, switch_model.solve
    indir = 'inputs_annual'
    outdir = 'outputs_annual_smoothed_redo'  # reused elsewhere when debugging
    sys.argv=[
        'switch solve',
        '--inputs-dir', indir,
        '--outputs-dir', outdir,
        '--reload-prior-solution',
        '--no-post-solve',
        # '--input-alias', 'gen_build_costs.csv=gen_build_costs_no_new_thermal.csv'
        # '--exclude-module', 'switch_model.hawaii.fed_subsidies'
    ]
    sys.argv = [
        'switch solve',
        '--inputs-dir', 'inputs_annual',  # abt. 3 mins to construct, 2 more to load solution
        '--outputs-dir', '/tmp/outputs_annual_smoothed',
        '--reload-prior-solution',
        '--input-alias', 'gen_build_predetermined.csv=gen_build_predetermined_adjusted.csv',
        '--exclude-module', 'switch_model.hawaii.heco_outlook_2019',
        '--ph-mw', '150', '--ph-year', '2022',
        # '--include-module', 'switch_model.hawaii.smooth_dispatch',
        # '--no-post-solve',
    ]
    sys.argv = [
        'switch solve',
        '--inputs-dir', 'inputs_annual',  # abt. 3 mins to construct, 2 more to load solution
        '--outputs-dir', 'outputs_annual_smoothed_redo',
        '--reload-prior-solution',
        '--input-alias',
            'gen_build_predetermined.csv=gen_build_predetermined_adjusted.csv',
            'generation_projects_info.csv=generation_projects_info_adjusted.csv',
        '--ph-mw', '150', '--ph-year', '2045',
        '--exclude-module', 'switch_model.hawaii.heco_outlook_2020_06',
        '--exclude-module',
            'switch_model.hawaii.save_results',
            'switch_model.reporting',
            'summarize_results',
        '--include-module',
            'switch_model.hawaii.smooth_dispatch',
            'switch_model.hawaii.save_results',
            'switch_model.reporting',
            'summarize_results',
        '--no-post-solve',
    ]
    sys.argv = [
        'switch solve',
        '--inputs-dir', 'inputs_2019_2022',
        '--outputs-dir', 'outputs_2019_2022',
        '--reload-prior-solution',
        '--input-alias',
            'gen_build_predetermined.csv=gen_build_predetermined_adjusted.csv',
            'generation_projects_info.csv=generation_projects_info_adjusted.csv',
        '--ph-mw', '0', '--ph-year', '2022',
        '--exclude-module', 'switch_model.hawaii.heco_outlook_2020_06',
        '--exclude-module',
            'switch_model.hawaii.save_results',
            'switch_model.reporting',
            'summarize_results',
        '--include-module',
            'switch_model.hawaii.smooth_dispatch',
            'switch_model.hawaii.save_results',
            'switch_model.reporting',
            'summarize_results',
        '--no-post-solve',
    ]
    m = switch_model.solve.main()
    # m.post_solve()

    # sys.argv.extend([
    #     '--exclude-module', 'switch_model.hawaii.smooth_dispatch',
    #     '--outputs-dir', '/tmp/outputs_annual_unsmoothed',
    # ])
    # mu = switch_model.solve.main()
    # post_solve(m, outdir)
