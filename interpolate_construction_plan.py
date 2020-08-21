"""
Create a schedule of capacity online in various tech groups:
- use tech groups from heco_outlook_2019
- start with minimum targets from heco_outlook_2019
- increase to match capacity online of each group in construction plan from
  solved optimization model
- increase in interim years in 2023-2044 to smooth step-ups in 2025, 2030, etc.
- take account of gen_build_predetermined in optimization model

Then advance BuildGen and BuildStorageEnergy proportionally from all matching
projects from next period year to satisfy the capacity target for interim years
(one by one). Be sure not to overbuild in any individual project (e.g., if
project is scheduled for reconstruction in a period year but we need more
capacity in an  earlier interim year).

Maybe do this as slices of project capacity that are online from date x through
date y: can slide the whole slice earlier as needed, but don't open a gap. Or
could be simpler: slide bottom n MW of project capacity forward; this applies to
the bottom n MW in all future years, even ...

To fill interim year:
- go through net capacity increases in next period (capacity built minus capacity retired > 0)
  - move some or all of the new build up to the current year
  - cascade to retirement year, moving up to the same amount of (re)build forward to close gap
  - keep cascading (with possibly diminishing block size) until end of study
  - this can only decrease, not increase, capacity online in a particular project
    in any future year
- repeat until interim year is filled

Will also need to slide replacement construction earlier to match actual retirement
year rather than next active period (for projects built in non-5 years, before
study or in 2022). i.e., step 1 is to start with build/operate schedule as given,
including automatic continuance of projects to 5-year mark, then shorten life
of the automatically continued projects to actual 30 year mark, cascading the
rebuilds into earlier years too.

(Set BuildStorageEnergy based on fixed energy/power ratio when needed, or maybe
just leave it blank.)

Note: we assume the following (add code to verify):
- construction plan is strictly increasing in the relevant groups
- relevant groups do not have discrete construction restrictions

Then add the BuildGen and BuildStorageEnergy values to
gen_build_predetermined.csv for each slice.


Note: we have a weird assumption that OffshoreWind can only be built in chunks
of 200 MW per period, but that would be spread out at 100+ MW/year in prior
years. It might be neater to just enforce the 200 MW limit when interpolating,
rather than allowing a lower limit here.
"""

"""
TODO:
- automatically extend life of plants that retire and are not rebuilt, up to the
  standard ending point in main model; also add assertion that there is only one
  instance of this in the model (could be a little more general by cloning the
  generator to extend the life, but that wouldn't gain much; add a note that
  this would be the solution if the assertion fails; but then you should
  probably do something similar for renewables instead of sliding them forward,
  and then you would be on a different path from what we've done; could instead
  generalize by only stretching/cloning slices of capacity that are followed by
  a decline; anyway, this gets messy) (or just add a line to do this manually
  for a list of plants, e.g., Schofield built in 2018 should continue to 2050)
  (see long printed note below and treatment of Schofield at the end.)
"""

import os, json, collections, argparse
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument('--heco-plan', action='store_true', default=False,
    help='Setup for HECO plan instead of Switch-optimized')
# parser.add_argument('--heco-retirements', action='store_true', default=False,
#     help='Use data in *_heco_retirements instead of *')
cmd_line_args = parser.parse_args()

if cmd_line_args.heco_plan:
    base_input_path = lambda *args: os.path.join('inputs_heco', *args)
    base_output_path = lambda *args: os.path.join('outputs_heco', *args)
    new_input_path = lambda *args: os.path.join('inputs_annual_heco', *args)
    new_output_path = lambda *args: os.path.join('outputs_annual_heco', *args)
# elif cmd_line_args.heco_retirements:
#     # untested, needs code in get_scenario_data and scenarios.txt to create
#     # the input and output dirs
#     base_input_path = lambda *args: os.path.join('inputs_heco_retirements', *args)
#     base_output_path = lambda *args: os.path.join('outputs_heco_retirements', *args)
#     new_input_path = lambda *args: os.path.join('inputs_annual_heco_retirements', *args)
#     new_output_path = lambda *args: os.path.join('outputs_annual_heco_retirements', *args)
else:
    base_input_path = lambda *args: os.path.join('inputs', *args)
    base_output_path = lambda *args: os.path.join('outputs', *args)
    new_input_path = lambda *args: os.path.join('inputs_annual', *args)
    new_output_path = lambda *args: os.path.join('outputs_annual', *args)


# new_input_path = lambda *args: os.path.join('inputs_2019_2022', *args)
# new_output_path = lambda *args: os.path.join('outputs_2019_2022', *args)
if not os.path.exists(new_output_path()):
    os.makedirs(new_output_path())

study_years = list(range(2020, 2050+1))
# could use actual years from study like below, but some code would need to be
# updated to find matching values from this list instead of using range()
# functions
# study_years = pd.read_csv(new_input_path('periods.csv'))['INVESTMENT_PERIOD'].to_list()

with open(base_output_path('heco_outlook.json')) as f:
# with open('/tmp/tagged/heco_outlook.json') as f:
    # print("\n>>>>>>>>>>>>> WARNING: using {}\n".format(f.name))
    targets = json.load(f)

tech_group_power_targets = targets['tech_group_power_targets'] # existing projects are added later
tech_group_energy_targets = targets['tech_group_energy_targets']
techs_for_tech_group = targets['techs_for_tech_group']
tech_tech_group = targets['tech_tech_group']
last_definite_target = targets['last_definite_target']

storage_techs = [t for t in techs_for_tech_group.keys() if 'battery' in t.lower()]
assert sorted(storage_techs)==['Battery_Bulk', 'Battery_Conting', 'Battery_Reg', 'DistBattery'], \
    'storage techs are not as expected'
assert all(techs_for_tech_group[t]==[t] for t in storage_techs), \
    'Code needs to be updated for grouped storage technologies'

# get build and retirement schedule from outputs dir
# need to get periods, tech, max age, BuildGen, BuildStorageEnergy
periods = (
    pd.read_csv(base_input_path('periods.csv'))
    .rename({'INVESTMENT_PERIOD': 'period'}, axis=1)
    .set_index('period')
)
# TODO: use periods['period_start'] where needed instead of periods themselves
assert all(periods.index==periods['period_start']), \
    'New code is needed to use periods with labels that differ from period_start'

build_gen = (
    pd.read_csv(base_output_path('BuildGen.csv'))
    .rename({'GEN_BLD_YRS_1': 'gen_proj', 'GEN_BLD_YRS_2': 'bld_yr'}, axis=1)
    .set_index(['gen_proj', 'bld_yr'])['BuildGen']
)
build_storage = (
    pd.read_csv(base_output_path('BuildStorageEnergy.csv'))
    .rename({
        'STORAGE_GEN_BLD_YRS_1': 'gen_proj',
        'STORAGE_GEN_BLD_YRS_2': 'bld_yr'
    }, axis=1)
    .set_index(['gen_proj', 'bld_yr'])['BuildStorageEnergy']
)
gen_info = (
    pd.read_csv(base_input_path('generation_projects_info.csv'))
    .rename({'GENERATION_PROJECT': 'gen_proj'}, axis=1)
).set_index('gen_proj')
gen_info['tech_group'] = gen_info['gen_tech'].map(tech_tech_group)
gen_info = gen_info[gen_info['tech_group'].notna()]
existing_techs = (
    pd.read_csv(base_input_path('gen_build_predetermined.csv'), na_values=['.'])
    .rename({'GENERATION_PROJECT': 'gen_proj'}, axis=1)
    .set_index('gen_proj')
    .join(gen_info, how='inner')
    .groupby(['build_year', 'tech_group'])[['gen_predetermined_cap', 'gen_predetermined_storage_energy_mwh']].sum()
    .reset_index()
)

gen_max_age = gen_info['gen_max_age']
gen_tech_group = gen_info['tech_group']
tech_group_max_age = (
    gen_info.loc[:, ['tech_group', 'gen_max_age']]
    .drop_duplicates().set_index('tech_group')
    .iloc[:, 0]
)
assert not any(tech_group_max_age.index.duplicated()), \
    "Some technologies have mixed values for gen_max_age."

gen_min_build_capacity = gen_info['gen_min_build_capacity']
tech_group_min_build_capacity = (
    gen_info.loc[:, ['tech_group', 'gen_min_build_capacity']]
    .drop_duplicates().set_index('tech_group')
    .iloc[:, 0]
)
assert not any(tech_group_min_build_capacity.index.duplicated()), \
    "Some technologies have mixed values for gen_min_build_capacity."

# append existing techs to targets
tech_group_power_targets = [
    [y, t, mw, 'existing']
    for i, y, t, mw, mwh in existing_techs.itertuples()
] + tech_group_power_targets

tech_group_energy_targets = [
    [y, t, mwh, 'existing']
    for i, y, t, mw, mwh in existing_techs.itertuples()
    if mwh > 0.0
] + tech_group_energy_targets


# 1. fill in all scheduled builds
# 2. check for extended retirements and slide forward
# 3. when to make the outer envelope?
# **** problem: if generation is expected to retire late and we move it to the
# correct year (which we must do, since the annual production cost model will
# not apply the life-extension), then we may create a capacity shortfall for a
# few years; for now we just assume there will be enough later builds to fill it.


# Calculate the capacity level for each tech_group

# set minimum capacity:
# early years:
# - existing capacity + HECO outlook (early build and replacements)
#   - may be more than Switch plan b/c early builds in HECO outlook get
#     scheduled into next study period
# later years:
# - Switch capacity plan

# HECO planned capacity, including pre-existing (may be a little earlier than
# Switch because Switch groups individual years into the following investment
# period)
heco_power_targets = (
    pd.DataFrame(index=techs_for_tech_group.keys(), columns=study_years)
    .fillna(0.0)
)
heco_energy_targets = (
    pd.DataFrame(index=storage_techs, columns=study_years)
    .fillna(0.0)
)
for heco_targets, group_targets in [
    (heco_power_targets, tech_group_power_targets),
    (heco_energy_targets, tech_group_energy_targets)
]:
    for year, tech_group, target, label in group_targets:
        # year, tech_group, target = tech_group_power_targets[0]
        first_year = max(year, study_years[0])
        last_year = min(
            year + tech_group_max_age[tech_group] - 1,
            study_years[-1]
        )
        try:
            heco_targets.loc[tech_group, first_year:last_year] += target
        except:
            print("ERROR")
            import pdb; pdb.set_trace()


# Capacity built in optimization model (includes pre-existing capacity)
switch_power_targets = (
    pd.DataFrame(index=techs_for_tech_group.keys(), columns=study_years)
    .fillna(0.0)
)
switch_energy_targets = (
    pd.DataFrame(index=storage_techs, columns=study_years)
    .fillna(0.0)
)
for build_info, switch_targets in [
    (build_gen, switch_power_targets),
    (build_storage, switch_energy_targets)
]:
    for (gen, year), target in build_info.items():
        # (gen, year), target = list(build_gen.items())[3]
        # (gen, year), target = list(build_gen.items())[2]
        # (gen, year), target = list(build_gen.items())[6]
        if gen not in gen_info.index:
            # this gen is not in a tech_group, ignore it
            continue
        first_year = max(year, study_years[0])
        last_year = year + gen_max_age[gen] - 1
        # extend to next period or end of study, as Switch does
        if last_year < periods.index[-1]:
            last_year = periods.index[
                periods.index.get_loc(last_year + 1, method='backfill')
            ] - 1
        else:
            last_year = study_years[-1]
        switch_targets.loc[gen_tech_group[gen], first_year:last_year] += target

for tdf in [heco_power_targets, heco_energy_targets, switch_power_targets, switch_energy_targets]:
    tdf.index.name = 'tech_group'
    tdf.columns.name = 'year'

# use maximum target from each source as the active target
power_targets = pd.concat([switch_power_targets, heco_power_targets]).max(level=0)
energy_targets = pd.concat([switch_energy_targets, heco_energy_targets]).max(level=0)
# power_targets.loc['Battery_Bulk', :]
# energy_targets.loc['Battery_Bulk', :]
# switch_power_targets.loc['Battery_Bulk', :]
# switch_energy_targets.loc['Battery_Bulk', :]

# now need to smooth LargePV, OnshoreWind, OffshoreWind and Battery_Bulk
# (leave DistPV and DistBattery on current schedule).
# Then reschedule construction for these techs to match the power_targets.
# All other techs: follow construction plan given by Switch (with different
# construction plans or techs it might be necessary to shift reconstruction
# earlier for techs built in off-years, i.e., pre-existing or built in 2022,
# with retirement (and rebuilding) on off year)

# interpolate these targets after 2022 to avoid stairsteps;
# respect minimum chunk size if specified
interpolate_tech_groups = ['LargePV', 'OnshoreWind', 'OffshoreWind', 'Battery_Bulk']
min_increment_size = {'OffshoreWind': 100}
# meet these targets as-is, without interpolation (but adjust from base model
# to match HECO outlook, which is already interpolated)
# (It may be possible to eliminate or be sharper about the distinction between
# interpolate and shift-only tech groups, because we now avoid interpolation
# anytime there is a specific plan for a tech, as there is for DistPV and
# DistBattery.)
print("""
    WARNING: it is not clear how to handle new thermal capacity in
    interpolate_construction_plan.py.
    We create targets based on the HECO and Switch construction schedules
    (whichever is greater). This includes the extended dates for life of off-
    year renewable construction (otherwise there would be holes at the end of
    these lives). Then we shift blocks earlier to match the targets for
    individual early years. This works OK for renewables because the targets are
    ascending (i.e., we always rebuild existing renewables and renewables
    specified in the HECO plan, and Switch generally has ascending amounts of
    renewables). But there is a problem if this is applied to IC_Schofield,
    which is built early but not rebuilt. So then the 5-year Switch model has
    IC_Schofield in 2048-49, (establishing a target in these years), but the
    annual model does not (since it's not rebuilt). This gives "WARNING: some
    power targets were missed". We currently avoid this by leaving CC/IC
    projects out of the non_interpolate_tech_groups. But then there will be a
    hole if any of them is built in an off year early enough to need rebuilding
    before 2050 and then rebuilt on a 5-year mark in the 5-year model (e.g., if
    IC_Schofield is wanted in 2050+). Another solution might be to include these
    in non_interpolate_tech_groups, but don't report errors if they have
    decreasing capacity in later years and don't meet the targets (i.e., let
    them retire before the 5-year mark, just as we do with Kahe, Waiau, etc.).
    But this could create infeasibility if some other type of thermal capacity
    was scheduled to take over when one of these retires in the 5-year model,
    since the online date of the replacement capacity isn't shifted forward.
    Maybe we should have a super- class of thermal capacity, and move
    closest-matching new capacity up to fill in the earlier real-world
    retirement date for Schofield?
""")
non_interpolate_tech_groups = [
    'DistPV', 'DistBattery', 'Battery_Reg', 'Battery_Conting',
    'CC_152', 'IC_Barge', 'IC_MCBH', 'IC_Schofield'
]
# all others will be built as scheduled by the optimization model

# don't interpolate if using HECO plan (just slide to correct start date)
if cmd_line_args.heco_plan:
    non_interpolate_tech_groups += interpolate_tech_groups
    interpolate_tech_groups = []

# only consider relevant technologies
power_targets = power_targets.loc[
    interpolate_tech_groups + non_interpolate_tech_groups, :
]

print("NOTE: interpolating LargePV from 2030 back to 2026, not 2025; there may be a dip in uptake.")
# raise NotImplementedError(
#     "May need to interpolate LargePV from 2030 back to 2025, not 2026."
# )
# May be able to put the following code at the top of the prev, current loop
# below, but first check if it's needed (may be easiest just to allow a dip in
# 2025).
# # Interpolate 2030 LargePV back to 2025 instead of 2026, to fill in a
# # dip in the 2025 forecast.
# if prev==2025 and current==2030:
#     prev = 2024

for targets in [power_targets, energy_targets]:
    # make sure targets are increasing (possibly with rounding error)
    if targets.diff(axis=1).min(axis=1).min() < -1e9:
        raise ValueError(
            'This script requires that all targets are increasing from year '
            'to year. This requirement is not met for {}.'
            .format(targets.diff(axis=1).min(axis=1).argmin())
        )

    # drop targets between investment periods after the last fixed target,
    # then interpolate to create smoothly increasing targets
    interp_groups = [g for g in interpolate_tech_groups if g in targets.index]
    for tech_group in interp_groups:
        for prev, current in zip(periods.index[:-1], periods.index[1:]):
            # delay interpolation until after any fixed targets, but not beyond
            # current year
            prev = min(current - 1, max(prev, last_definite_target.get(tech_group, prev)))
            # enforce min_increment_size if needed
            if tech_group in min_increment_size:
                max_steps = (
                    targets.loc[tech_group, current]
                    - targets.loc[tech_group, prev]
                ) // min_increment_size[tech_group]
                prev = max(current - max_steps, prev)
            if current - prev < 2:  # number of steps
                continue # nothing to interpolate

            # blank out the years that will get interpolated (between prev and
            # current)
            targets.loc[tech_group, prev+1:current-1] = float('nan')

            # This is where the interpolation happens:
            # capacity targets have been set for years where applicable, with
            # nans in between. Now we interpolate intermediate capacity targets to
            # replace those nans. Later, construction each year will be adjusted to
            # meet these target annual capacity levels.
            targets.loc[tech_group, :] = targets.loc[tech_group, :].interpolate()

# adjust construction plans to meet targets
# To increase construction in early year:
# - go through net capacity increases in next period (capacity built minus capacity retired > 0)
#   - move some or all of the new build up to the current year
#   - cascade to retirement year, moving up to the same amount of (re)build forward to close gap
#   - keep cascading (with possibly diminishing block size) until end of study
#   - this can only decrease, not increase, capacity online in a particular project
#     in any future year
# - repeat until interim year is filled

# Find additions and retirements in Switch in each period, taking account of the
# life-extensions used in the optimization model.
# Then slide the end points forward to eliminate the life extensions (because
# those won't be used in the production cost model).
# Then slide excess capacity forward as needed to meet the targets.

def move_build(build, gen_proj, cap, from_year, to_year):
    """
    Move construction of cap MW of gen_proj from from_year to to_year,
    also moving any reconstructions of the same or less capacity currently
    scheduled for the retirement year.

    gen_proj = 'Oahu_Battery_Bulk'
    tech_group = 'Battery_Bulk'
    cap = 75
    from_year = 2020
    to_year = from_year - 3
    build = collections.defaultdict(lambda: collections.defaultdict(float))
    build[tech_group, from_year][gen_proj] = 100
    build[tech_group, from_year+gen_max_age[gen_proj]][gen_proj] = 50

    move_build(build, gen_proj, cap, from_year, to_year)

    defaultdict(<function __main__.<lambda>()>,
            {('Battery_Bulk', 2020): defaultdict(float,
                         {'Oahu_Battery_Bulk': 25}),
             ('Battery_Bulk', 2035): defaultdict(float,
                         {'Oahu_Battery_Bulk': 0}),
             ('Battery_Bulk', 2017): defaultdict(float,
                         {'Oahu_Battery_Bulk': 75.0}),
             ('Battery_Bulk', 2032): defaultdict(float,
                         {'Oahu_Battery_Bulk': 50.0})})

    # 2032 capacity will retire in 2047; shift to 2030 and get some rebuild
    move_build(build, gen_proj, 30, 2032, 2030)
    defaultdict(<function __main__.<lambda>()>,
                {('Battery_Bulk', 2020): defaultdict(float,
                             {'Oahu_Battery_Bulk': 25}),
                 ('Battery_Bulk', 2035): defaultdict(float,
                             {'Oahu_Battery_Bulk': 0}),
                 ('Battery_Bulk', 2017): defaultdict(float,
                             {'Oahu_Battery_Bulk': 75.0}),
                 ('Battery_Bulk', 2032): defaultdict(float,
                             {'Oahu_Battery_Bulk': 20.0}),
                 ('Battery_Bulk', 2030): defaultdict(float,
                             {'Oahu_Battery_Bulk': 30.0}),
                 ('Battery_Bulk', 2045): defaultdict(float,
                             {'Oahu_Battery_Bulk': 30.0})})
    """
    tech_group = gen_tech_group[gen_proj]
    retire_year = from_year + gen_max_age[gen_proj]
    new_retire_year = retire_year + (to_year - from_year)
    build[tech_group, from_year][gen_proj] -= cap
    build[tech_group, to_year][gen_proj] += cap
    if retire_year <= study_years[-1]:
        # how much of this was scheduled to be rebuilt in the original
        # retirement year?
        cascade_cap = min(cap, build[tech_group, retire_year][gen_proj])
        # move that amount up to the new retirement year
        move_build(build, gen_proj, cascade_cap, retire_year, new_retire_year)
    elif new_retire_year <= study_years[-1]:
        # reconstruct projects that have been moved earlier, creating gaps at
        # the end of the study
        build[tech_group, new_retire_year][gen_proj] += cap
    print(
        "Moved {} units of {} from {} to {}."
        .format(cap, gen_proj, from_year, to_year)
    )
    return build

def clean_build_dict(build):
    """ strip out zero-value records from the build dict """
    for k, d in list(build.items()):
        for g, q in list(d.items()):
            if not q:
                del d[g]
        if not d:
            del build[k]

# store by proj, but later need to find all projects in a particular
# tech_group that have capacity available in a particular year, so structure
# should be
# build = {(tech_group, year): {gen1: amt, gen2: amt, ...}, ...}
# retire = check build[tech_group, year-max_age][gen1]
# To update: set build[tech_group, year][gen1]
build_gen_dict = collections.defaultdict(lambda: collections.defaultdict(float))
build_storage_dict = collections.defaultdict(lambda: collections.defaultdict(float))
for (gen, year), cap in build_gen.items():
    if gen in gen_info.index and cap > 0:
        build_gen_dict[gen_tech_group[gen], year][gen] += cap
for (gen, year), cap in build_storage.items():
    if gen in gen_info.index and cap > 0:
        build_storage_dict[gen_tech_group[gen], year][gen] += cap

for build, build_targets in [
    (build_gen_dict, power_targets),
    (build_storage_dict, energy_targets)
]:
    # Find mid-period retirements and shift the subsequent reconstruction earlier
    to_fix = []  # tuple of gen_proj, capacity, old build date, new build date
    for prev_period, cur_period in zip(periods.index[:-1], periods.index[1:]):
        for gen in gen_info.index:
            # prev_period = 2040; cur_period = 2045; gen = 'Oahu_OnshoreWind_OnWind_Kahuku'; y = 2011
            age = gen_max_age[gen]
            tech_group = gen_tech_group[gen]
            # build years that could have had service extended to this period
            ext_build_years = list(range(prev_period - age + 1, cur_period - age))
            shiftable_cap = build[tech_group, cur_period][gen]
            for y in ext_build_years:
                if shiftable_cap == 0:
                    break # no possibility of shifting any more
                shift_cap = min(build[tech_group, y][gen], shiftable_cap)
                if shift_cap > 0:
                    # shift this much capacity from current period to correct rebuild year
                    to_fix.append((gen, shift_cap, cur_period, y+age))
                    # update tally of remaining shiftable capacity
                    shiftable_cap -= shift_cap
    clean_build_dict(build)

    # update build plan as needed (must start at latest build date so those get
    # attached to the previous build and then move earlier when that gets moved up)
    for gen, cap, from_year, to_year in sorted(to_fix, key=lambda x: x[2], reverse=True):
        move_build(build, gen, cap, from_year, to_year)

    # update to meet target...
    # tech_group = 'LargePV'; target_year = 2020; target_cap = 175.69; age = 30

    for tech_group, targets in build_targets.iterrows():
        age = tech_group_max_age[tech_group]
        for target_year, target_cap in targets.items():
            actual_cap = sum(
                sum(d.values())
                for (tg, y), d in build.items()
                if tg == tech_group and y <= target_year < y + age
            )
            if actual_cap > target_cap + 1e-9:
                print(
                    "WARNING: installed {} capacity in {} is "
                    "{}, which exceeds target of {}."
                    .format(tech_group, target_year, actual_cap, target_cap)
                )
            # elif actual_cap == target_cap:
            #     print(
            #         "installed {} capacity in {} is {}, which equals the target."
            #         .format(tech_group, target_year, actual_cap)
            #     )
            elif actual_cap < target_cap - 1e9:
                print(
                    "installed {} capacity in {} is "
                    "{}, which is below target of {}."
                    .format(tech_group, target_year, actual_cap, target_cap)
                )

            # find later installations (not reconstructions) in this tech_group
            # and shift them earlier
            for year in range(target_year+1, study_years[-1]+1):
                for gen, cap in build[tech_group, year].items():
                    if actual_cap >= target_cap:
                        break  # finished adjusting
                    cap_added = cap - build[tech_group, year-gen_max_age[gen]][gen]
                    if cap_added > 0:
                        shift_cap = min(cap_added, target_cap-actual_cap)
                        move_build(build, gen, shift_cap, year, target_year)
                        actual_cap += shift_cap
    clean_build_dict(build)

# export as predetermined build schedule for an extensive model (could instead
# be done for multiple one-year models)
# set a predetermined value for all possible build years
build_costs = (
    pd.read_csv(new_input_path('gen_build_costs.csv'))
    .set_index(['GENERATION_PROJECT', 'build_year'])
)
gen_build_predetermined = (
    pd.read_csv(new_input_path('gen_build_predetermined.csv'))
    .set_index(['GENERATION_PROJECT', 'build_year'])
    .reindex(build_costs.index)  # set a value for every possible build year
    .fillna(0.0)
)
gen_build_predetermined['gen_predetermined_storage_energy_mwh'] = float('nan')

# start with original construction plan
for (gen, year), cap in build_gen.items():
    gen_build_predetermined.loc[(gen, year), 'gen_predetermined_cap'] = cap
for (gen, year), cap in build_storage.items():
    gen_build_predetermined.loc[(gen, year), 'gen_predetermined_storage_energy_mwh'] = cap
# update interpolated projects
for gen, tech_group in gen_tech_group.items():
    for year in study_years:
        cap = build_gen_dict[tech_group, year][gen]
        gen_build_predetermined.loc[(gen, year), 'gen_predetermined_cap'] = cap
        if tech_group in storage_techs:
            gen_build_predetermined.loc[(gen, year), 'gen_predetermined_storage_energy_mwh'] \
            = build_storage_dict[tech_group, year][gen]

# gen_build_predetermined.loc['Oahu_Battery_Bulk', :]
# build_storage['Oahu_Battery_Bulk']
# build_gen['Oahu_Battery_Bulk']
# sorted([(y, b) for ((t, y), b) in build_gen_dict.items() if t == 'LargePV' and y <= 2020])
# sorted([(y, c) for (p, y), c in build_gen.iteritems() if 'TrackingPV' in p and y <= 2020])
# sorted((year, power_cap) for (gen, year), (power_cap, energy_cap) in gen_build_predetermined.iterrows() if 'TrackingPV' in gen and year <= 2020)

# check that we're actually hitting the targets
power_online = power_targets.copy()
power_online.loc[:, :] = 0.0
energy_online = energy_targets.copy()
energy_online.loc[:, :] = 0.0
for (gen, year), (power_cap, energy_cap) in gen_build_predetermined.iterrows():
    tech_group = gen_tech_group.get(gen, None)
    if tech_group in power_online.index:
        power_online.loc[tech_group, year:year+gen_max_age[gen]-1] += power_cap
    if tech_group in energy_online.index:
        energy_online.loc[tech_group, year:year+gen_max_age[gen]-1] += energy_cap
if (power_online - power_targets).abs().max().max() > 0.001:
    print("\nWARNING: some power targets were missed\n")
if (energy_online - energy_targets).abs().max().max() > 0.001:
    print("\nWARNING: some energy targets were missed\n")

# pd.DataFrame({'online': power_online.loc['LargePV', :], 'target': power_targets.loc['LargePV', :]})
# gen_build_predetermined

# # check that there's never excess development
# gen_cap_online = pd.DataFrame(index=gen_info.index, columns=study_years).fillna(0.0)
# for (gen, year), (power_cap, energy_cap) in gen_build_predetermined.iterrows():
#     if gen in gen_cap_online.index:
#         gen_cap_online.loc[gen, year:year+gen_max_age[gen]-1] += power_cap
# assert gen_cap_online.sub(gen_info['gen_capacity_limit_mw'], axis=0).max().max() < 0.000000001, "some capacity limits were exceeded"
# max is 5.6e-14, which should be within rounding error

# trim any minor excess development; report major errors
for (gen, year), (power_cap, energy_cap) in gen_build_predetermined.iterrows():
    if gen in gen_max_age:
        cap_online = (
            gen_build_predetermined
            .sort_index()
            .loc[(gen, slice(year-gen_max_age[gen]+1, year)), 'gen_predetermined_cap']
            .sum()
        )
        max_cap = gen_info.loc[gen, 'gen_capacity_limit_mw']
        excess_cap = cap_online - max_cap
        if excess_cap > 0.00001:
            raise ValueError(
                'Excess capacity scheduled for {} in {}: {} > {}.'
                .format(gen, year, cap_online, max_cap)
            )
        elif excess_cap > 0:
            # make a small adjustment
            gen_build_predetermined.loc[(gen, year), 'gen_predetermined_cap'] \
                -= excess_cap
            print(
                'Reduced construction of {} in {} from {} to {}.'
                .format(gen, year, power_cap, power_cap-excess_cap)
            )

# zero out any tiny values (positive or negative)
for c in ['gen_predetermined_cap', 'gen_predetermined_storage_energy_mwh']:
    gen_build_predetermined.loc[
        gen_build_predetermined[c].abs() < 1e-9,
        'gen_predetermined_cap'
    ] = 0


####################
# create capacity_additions_table.csv, showing all additions in
# an easy-to-read form

plans = pd.DataFrame()
for col, cap_type, targets in [
    (0, 'power', tech_group_power_targets),
    (1, 'energy', tech_group_energy_targets)
]:
    built_dict = collections.defaultdict(float)
    for (gen, year), build_cols in gen_build_predetermined.iterrows():
        tech_group = gen_tech_group.get(gen, gen[5:] if gen.startswith('Oahu_') else gen)
        built_dict[year, tech_group] += build_cols[col]
    built = pd.Series(built_dict)
    built.index.names = ['year', 'tech_group']
    plan = pd.DataFrame.from_records(
        targets, columns=['year', 'tech_group', 'capacity', 'label']
    ).groupby(['year', 'tech_group', 'label']).sum()
    planned_built = (
        plan.groupby(['year', 'tech_group'])['capacity'].sum()
        .reindex(built.index)
        .fillna(0.0)
    )
    switch_built = built - planned_built
    planned_built[(2030, 'OnshoreWind')]
    switch_built[switch_built.abs() < 1e-9] = 0.0
    switch_plan = switch_built.to_frame(name='capacity')
    # switch_plan.loc[(2029, 'OnshoreWind'), :]
    switch_plan['label'] = 'Switch'
    switch_plan = switch_plan.set_index('label', append=True)
    # switch_plan.loc[(2029, 'OnshoreWind', 'Switch'), :]
    plan = plan.append(switch_plan)
    # plan.loc[(2029, 'OnshoreWind', 'Switch'), :]
    plans[cap_type] = plan['capacity']
    # plans.loc[(2029, 'OnshoreWind', 'Switch'), :]

# plans.loc[(2029, 'OnshoreWind', 'Switch'), :]

def capacity_str(r):
    out = '{:.1f}'.format(r['power'])
    if not pd.np.isnan(r['energy']):
        # if r['power'] == 0:
        #     out += '/{:.1f}MWh'.format(r['energy'])
        # else:
        #     out += '/{:.1f}h'.format(r['energy']/r['power'])
        out += ' MW/{:.1f} MWh'.format(r['energy'])
    out += '\n({})'.format(r['label'])
    return out

# TODO:
# existing thermal capacity is labeled as Switch additions
# may want to show retirements in addition to construction? (not for now, would
# require first approach below to fit in all the thermal plants)

plan_tab = plans.reset_index().query(
    'year >= 2020 and (power > 0 or energy > 0) '
    'and not label.str.startswith("rebuild")'
)
plan_tab['capacity'] = plan_tab.apply(capacity_str, axis=1)
# plan_tab.loc[(2029, 'OnshoreWind'), :]
plan_tab = plan_tab.groupby(['year', 'tech_group'])['capacity'].agg(lambda x: '\n'.join(x))
# plan_tab.loc[(2029, 'OnshoreWind'), :]
plan_tab = plan_tab.unstack(['tech_group']).fillna('').sort_index(axis=0).sort_index(axis=1)
# plan_tab.loc[2029, 'OnshoreWind']
plan_tab = plan_tab.reindex(['LargePV', 'Battery_Bulk', 'DistPV', 'DistBattery', 'OnshoreWind', 'OffshoreWind'], axis=1)
plan_tab.columns = ['Large PV', 'Large Battery', 'Dist PV', 'Dist Battery', 'Onshore Wind', 'Offshore Wind']
plan_tab.to_csv(new_output_path('capacity_additions_table.csv'))

print("\n\nNeed to add pumped storage to capacity_additions_table.csv manually.")
print("Need to remove rebuilds of Switch-selected assets from capacity_additions_table.csv manually. (should really fix this in code)\n")

# from IPython.display import display, HTML
# display(HTML(plan_tab.to_html().replace("\\n","<br>")))

# done with capacity_additions_table.csv
###################

# if annual study is short, we don't want to create extra rows
last_period = pd.read_csv(new_input_path('periods.csv'))['INVESTMENT_PERIOD'].max()

# Save "adjusted" version of input file; we don't save on top of the original
# in case we need to run this again, re-reading from the original.
gen_build_predetermined.query('build_year <= {}'.format(last_period)).to_csv(
    new_input_path('gen_build_predetermined_adjusted.csv'),
    na_rep='.'
)

# Save generation_project_info_adjusted.csv with gen_min_build_capacity
# set to min_increment_size or '.' for interpolated projects. This allows
# interpolation of projects with large minimum size per period into smaller
# chunks over a few years.
generation_projects_info = (
    pd.read_csv(new_input_path('generation_projects_info.csv'))
    .set_index('gen_tech', drop=False)
)
# this previously only considered techs in interpolate_tech_groups, but that
# creates some inconsistency between the HECO plan (where no techs are
# interpolated) and the Switch plan. But it's possible the HECO plan includes
# subblocks in adjacent years that add up to match a normal block size when
# the 5-year model is run, but would fail when the annual model is run. So we
# now adjust the minimum size whether a tech can be interpolated or not.
for tg, min_size in min_increment_size.items():
    if tg in techs_for_tech_group:
        for tech in techs_for_tech_group[tg]:
            if tech in generation_projects_info.index:
                generation_projects_info.loc[tech, 'gen_min_build_capacity'] = min_size
# Also extend the life of Schofield when using the standard plan. This was built
# in 2018 and has a 30 year life, so Switch assumes it will last until a 5-year
# mark during the optimization phase and doesn't add capacity to fill the gap in
# the last 2 years. This can cause infeasibility.
# TODO: generalize this, i.e., extend all thermal plants to the even-year mark
# (it may be better to slide subsequent rebuilds forward if they exist).
# TODO: also apply this to the HECO Plan (not as urgent because it has excess
# thermal capacity).
if not cmd_line_args.heco_plan:
    print("Updating IC_Schofield life to 32 years.")
    generation_projects_info.loc['IC_Schofield', 'gen_max_age'] = 32

generation_projects_info.to_csv(
    new_input_path('generation_projects_info_adjusted.csv'),
    na_rep='.', index=False
)
