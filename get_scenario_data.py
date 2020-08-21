#!/usr/bin/env python

from __future__ import print_function, division
import sys, os, argparse

import switch_model.hawaii.scenario_data as scenario_data


parser = argparse.ArgumentParser()
parser.add_argument('--skip-cf', action='store_true', default=False,
    help='Skip writing variable capacity factors file (for faster execution)')
parser.add_argument('--skip-ev-bids', action='store_true', default=False,
    help='Skip writing EV charging bids file (for faster execution)')
# default is daily slice samples for all but 4 days in 2007-08
parser.add_argument('--slice-count', type=int, default=0, # default=727,
    help='Number of slices to generate for post-optimization evaluation.')
parser.add_argument('--tiny-only', action='store_true', default=False,
    help='Only prepare inputs for the tiny scenario for testing.')

cmd_line_args = parser.parse_args()

# settings used for the base scenario
# (these will be passed as arguments when the queries are run)

# define scenarios
scenarios = [
    # base scenario
    '--scenario-name base --outputs-dir outputs',
    # allow new wind (up to 200 MW) or thermal
    '--scenario-name accept --exclude-module no_new_thermal_capacity --outputs-dir outputs_accept',
    # exclude any new onshore wind or thermal
    '--scenario-name resist --onshore-wind-limit 123 --outputs-dir outputs_resist',
    # HECO plan
    '--scenario-name heco --psip-force '
        '--exclude-module no_new_thermal_capacity switch_model.hawaii.heco_outlook_2020_08 '
        '--include-module switch_model.hawaii.heco_plan_2020_08 '
        '--inputs-dir inputs_heco --outputs-dir outputs_heco',
    # no hydro
    '--scenario-name no_hydro --ph-year 2045 --ph-mw 0',
    # optimized, but with HECO retirement dates
    '--scenario-name heco_retirement --inputs-dir inputs_heco --outputs-dir outputs_heco_retirement',
]
with open('scenarios.txt', 'w') as f:
    f.writelines(s + '\n' for s in scenarios)

print("""
TODO (soon):
+ = done
* = important
- = to do
x = won't do

DONE:
+ allow new thermal plants to be built (check how much that affects costs)
+ don't let IC plants run on LSFO (use diesel or higher)
+ run new CCGT on LSFO (HECO did in PSIP/RESOLVE so we assume this is the plan)
+ allow CIP to run on diesel, not just biodiesel; this page says it is biodiesel-only
  (https://www.hawaiianelectric.com/clean-energy-hawaii/our-clean-energy-portfolio/renewable-energy-sources/biofuels)
  but this page says it is diesel (https://www.hawaiianelectric.com/about-us/power-facts).
  EIA form 923 says it has used only regular diesel since Nov. 2018; in PSIP
  HECO modeled it as diesel till 2045 then biodiesel.
+ fix inputs to prevent biodiesel-listed plants from running on diesel (only affects Airport)
+ switch from EIA AEO 2019 to EIA AEO 2020 fuel price forecast
+ use clean transportation plan BAU charging times for light-duty EVs instead of UH's
+ don't allow construction of CC152 until 2025 (hasn't been proposed or gotten permits yet)
+ don't allow offshore wind before 2025
+ don't interpolate offshore wind from 2025 into earlier years
+ set 200 MW minimum size per increment for offshore wind
+ interpolate offshore wind to prior years in 100+ MW chunks
+ (1 hour) add a 2050-54 period (new time sample)
+ (2 hours) require Schofield to run on >= 50% biodiesel
  + switch fuel to diesel in input tables, then add a hawaii.schofield module
    that forces it to run on >= 50% rps-eligible fuel during each timepoint
+ (0.5 hour) make sure new CC plant is IPP-owned in RIST reporting
+ (1 more hour) Add plants that are in EIA tables but not in Switch (noted in Existing Plants workbook)
   + two small solar plants
   + two cogen thermal plants, burning waste oil and gas
     + for CO2 emissions and fuel cost, we model their fuel use as if it were LSFO,
       at the lower rate reported for cogen electricity production
     + then add enough variable O&M to get the PPA cost reported to the PUC in 2018
     + force them to run as baseload, since that is the historical pattern
     + assume they shutdown when refineries do (like we do for Kalaeloa)
+ (6 hours) compare Switch plant efficiencies (from HSIS) against fuel
  consumption reported in EIA form 923
  + keep most HSIS values but adjust AES incremental heat rate to match EIA
    full-load heat rate (much lower than HSIS; GE may not have had good data)
+ (0.1 hours) prevent construction of new onshore wind until 2027 and limit to 200 MW more (323 MW total)
+ (2 hours) double-check early wind/solar data (RFP 1 & 2) vs. HECO's April 2020
  emails and Murray and Samantha's May 2020 emails
+ apply 200 MW / 100 MW minimum size and 2030 (interpolated to 2029) earliest start date
  for offshore wind (Murray Clay email 5/23/20 20:56)
+ set maximum of 200 MW for additional onshore wind; delay till 2030 with interpolation to 2026-30
+ add Mauka Fit 1 and Aloha Solar Energy Fund II as non-DER, non-RFP, non-CBRE projects
+ (2 hours) decide whether to use HECO's retirement schedule from April 2020 emails
  (E3 Plan with Generator Modernization) or previous schedule (E3 Plan)
  + compare results of both; maybe stick with E3 Plan and wait for HECO to send
    retirement cost info
  + use longer dates from both: mainly Gen Mod plan but keep Kahe 5 & 6 online to 2045
+ check whether to use June 2018 DER forecast or March 2020; sticking with June
  2018 because there's no reason to expect 3-4 year stoppage of new Dist PV
+ look at HECO's April 2020 emails (also look at DER there)
+ apply Samantha Ruiz 5/26/20 08:37 email and others from same day
+ switch to using IGP EV adoption forecast instead of EoT forecast (Murray email
  5/18/20 9:18 am). Also use other elements discussed in this email.
+ prevent AES from burning pellet biomass to help meet the RPS in early years
+ run AES as baseload matching historical production, instead of allowing free
  operation (which gives about 20% more output)
+ check whether existing solar needs calibration
  + no, getting very good match for 2018 in Switch
  + main differences between Switch 2020 and real 2018 are
    + 2018 was a low-sun year (9%)
    + lots of PV capacity was added in 2019-2020
    + see "compare EIA-Switch solar production.xlsx"
+ calibrate existing wind to match existing plants' output
+ calibrate loads for 2019 instead of 2018
  + use current forecasts of EV and DistPV so gross load matches Switch well

+ run with new LSFO MMBtu/bbl numbers; this increases 2020 costs by about 14% of the 2019 expenditure
+ force commitment of Kahe 1-6 and Waiau 7-8 in 2020-22
  + add a "enable_must_run_before: 2023" setting to scenario_data
+ cap AES output to match historical outputs
    + make AES baseload and use 9.7% scheduled outage rate; this limits output to 90.3% of nameplate, matching average capacity factor in 2012-16. (Switch doesn't seem to enforce 100% dispatch of baseload plants except in no-commit mode.)
+ block Par and Tesoro from using biodiesel (only allow LSFO)
+ don't retrieve generic capital costs if existing solar projects have costs in the same year
+ document changes in scenario 2 and numbers for all additions - CBRE, RFP, Switch, etc.
  + see Murray Clay email 5/27/20 09:46
  + see Murray Clay email 5/18/20 09:21
  + see bottom of Murray Clay email 5/14/20 08:27

TO DO (compare HECO plan from 3/20):
- adjust early plan (maybe by removing elements from our plan when psip flag is set, then adding replacement elements as optional)
  - delay all CBRE Phase 2 to 2025
  - use generic 1300 GWh PV (560 MW) for Stage 2 RFP
  - or maybe just keep these as-is, since there is new information since 3/20
- use other elements from tech_group_targets_psip (--psip-force)
- retire Kahe 5 & 6 in 2029 (create alternative generation_projects_info (or dir))
- add flags to interpolate_construction_plan to
  - not interpolate, just set intermediate builds to zero
  - base off of generation_projects_info_late_kahe.csv instead of generation_projects_info.csv
- no pumped hydro

TO DO:

- find out why gen_timepoint_commit_bounds is not being set for 2022 in  the
  main inputs, even though it is set for 2020-22 in inputs_annual (doesn't
  affect annual evaluation or fixed early construction plan, but seems weird)

+ run scenario 2a (no new thermal, limited wind)
- change 2019-calibrated loads to just rescale HECO's peak and average forecasts
  by the same amount, keeping the same ratio they forecasted
  - EV estimate for 2019 was already updated slightly 6/11/20
- set H-Power and AES to produce same power as in 2018, not 2015 (H-Power) and 2012-16 (AES)
  - copy scheduled-outage rate formula from cogen plants to these ones
  - re-run import_data.generator_info
  - re-run this script
- don't allow smaller than 25 MW increments for onshore wind
  - overall and in interpolation script
  - see email from M Fripp to M Clay 5/25/20 20:26
  - watch out, this would prevent construction of Na Pua Makani
- don't allow more than 400 MW of offshore wind additions
  - per year or in total?
  - see email from M Fripp to M Clay 5/25/20 20:26

- why has average production for dist PV and utility-scale PV dropped so much
  since the 2016 PSIP presentations? Why has total dist PV resource risen?

- send data source updates to HECO
  - see bottom of Murray Clay email 5/23/20 20:56

LATER:
- report for 2019 in annual stage
- check whether there's a systematic difference between our sample days and the annual averages for load, wind, sun
  - may be enough just to check that our load matches HECO load
- create alternative scenarios for wind and thermal capacity
  - see Murray Clay email 5/25/20 20:08
  - see Murray Clay email 5/14/20 08:27
  - report on cost and RPS difference between these and main scenario

- (8 hours) include electric buses and trucks in model
  - need to merge simple EV charging behavior into advanced EV module
- (8 hours) optimize retirements of existing plants
 - requires new code and data from HECO on the cost to keep them open
 - maybe just experiment with mostly early vs. mostly late dates
 - see Murray Clay email 5/26/20 16:53

MUCH LATER
- restrict Airport DSG to 1500 hours/year
  - per application (p. 23) in docket 2008-0329
  - can be done pretty easily in hawaii.oahu_plants, but may need some debugging
- add startup fuel requirements for new thermal plants
  - Schofield is in RPS Study table, but others aren't; IC could be like
    Schofield and CC could be like CIP, Waiau 9/10 or Kalaeloa (or see HECO
    PSIP docs)

PROBABLY WON'T DO:
- (12 hours) benchmark system using 2017 data and revise our system
   - Check whether we run plants differently from actual experience
       - force commitment of all "baseload" plants if needed
- (8 hours) Do better per-MMBtu fuel cost comparison between Switch and HECO 10k in "../Switch-HECO-DBEDT cost comparisons.xlsx"
 - use 2018 test case
 - include only HECO production from LSFO, not cogen IPPs
 - also check for other explanations noted in draft e-mail to Erin Sowerby around 11/10/19 but not finished
- (? hours) Update PPA terms if we get O&M and historical PPA data and current load
 forecast from HECO (requested Dec. 2019)
 - will Kalaeloa contract be renewed?
   - PUC lists it as expired in 10/31/17
   - this article says they're on month-to-month while negotiating:
     - https://www.hawaiinewsnow.com/story/31931002/time-running-out-on-kalaeloa-partners-25-year-contract-with-heco/
 - do PPAs have capacity payments, curtailment terms, escalators over time and/or fuel-cost indexing?
   - AES is inflation-indexed; Kalaeloa is pegged to Asian crude prices: p. 7 of http://www.hei.com/interactive/newlookandfeel/1031123/annualreport2018.pdf
   - what about Tesoro Hawaii and Hawaii Cogen, which burn waste oil?
   - what about current wind and solar?
   - total expenditure on AES, Kalaeloa, HPOWER and aggregated wind and solar PPAs is shown on p. 105 of http://www.hei.com/interactive/newlookandfeel/1031123/annualreport2018.pdf
     - we could check that against production at each one in 2016-2018 to see if price varies between years
- (16 hours) use all available weather for post-optimization evaluation (not just 13 sample days)
- (4 hours) track biomass emissions separately from others (maybe give biodiesel, biomass
 and MSW direct emissions and negative upstream emissions)
- (6 hours) break existing wind and solar projects into individual projects with performance matching EIA and
  capital cost and/or fixed O&M that reproduce their PPA costs (rebuildable at future costs)
- (6 hours) derate or restrict use of AES and Kalaeloa to match historical levels
- (4 hours) Apply maintenance outages from GE RPS Study, as specified in documentation


NOT GOING TO DO:
x maybe input future RE costs as PPAs instead of capital/O&M and back end aggregation
x HECO says in PSIP (vol. 1 p. 4-3) that they will convert Honolulu 8 & 9 to
  synchronous condensers in 2021; we don't model this cost or effect (voltage
  support and inertia)
x adjust hourly weights for EV charging to obtain correct total EV load when
  timepoints are not hourly. e.g., average across matching hours (not doing
  because it's inconsistent with how we handle loads and weather)

DONE DECEMBER 2019:
+ use newer DER/DESS forecast
+ use newer EV charging cycle
+ interim technique for O&M:
  + use O&M costs from AEO 1996
  + apply to HECO generation in 2017 (EIA) and compare to total O&M reported by
    HECO on FERC Form 1, and split off a portion to use as "non-indexed O&M"
+ interim technique for PPAs:
  + for now, assume no capacity payment
  + calculate fuel expenditure for 2018 (if any) based on our fuel price data
    and EIA production and fuel consumption (form 923)
  + use fixed and variable O&M costs as above
  + adjust the capital cost to get PPA to match PUC PPAs in 2018
    + see p. 66 of https://puc.hawaii.gov/wp-content/uploads/2018/12/FY18-PUC-Annual-Report_FINAL.pdf

+ check HECO's data submissions, see if they answer all earlier questions

+ separate total PPA cost into intermittent (wind/solar) projects and all other
  + just add column identifying intermittent vs. not
+ disaggregate cost reporting (incl. ppa items) by vintage (extra column)
  + supports PIM assuming x percent of a year's new PPAs is savings vs PUC benchmark, of which y percent is returnable
  + PIM will need to key off tech start year to find the recent starts
  + probably create an inner loop over relevant build years for each tech
  + will need to assign some values by vintage:
    + amortization cost, fixed o&m, additions, retirements, capital outlay
  + will need to allocate some values across vintages (by share of existing capacity):
    + fuel, variable o&m, emissions

x convert AES to a PPA cost? (include it as fixed and variable O&M; but this doesn't allow fuel switching...)


Outstanding questions:
.- Will CBRE Phase 1 solar enter service in 2020?
.- Should we reduce DER forecast in light of HECO's projected shortfall reported in CBRE proceeding?
*** they don't know how much wind and/or solar they'll get in phase 2, could have both
.- How much solar should we expect on Oahu in CBRE Phase 2 and when?
.- Do we expect any wind on Oahu in CBRE Phase 2, and if so, when?
.- Is Na Pua Makani wind project 24 MW or 27 MW? (see https://www.napuamakanihawaii.org/fact-sheet/ vs PSIP and https://www.hawaiianelectric.com/clean-energy-hawaii/our-clean-energy-portfolio/renewable-project-status-board)
.- Will RFP Phase 2 include any wind or just solar?
.- How much storage is expected to be procured with RFP Phase 2 solar?
.- The PSIP included 90 MW of contingency battery in 2019, but that doesn't seem to be moving ahead. Should we assume this has been abandoned?
.- Can we get the business-as-usual charging profiles for light-duty EVs that HECO used for the Electrification of Transport study?
- Should Switch prioritize the best distributed PV locations or choose randomly?
- Should we include multi-month hydrogen storage in the scenario (currently don't)?
- Should we include Lake Wilson pumped storage hydro in the scenario (currently do)?
""")

# outtakes
# - debug infeasibility of current models: could be from 2050 period, could be from new rules in oahu_plants
#   - was old model preventing new build of LargePV until 2045? The latest target
#     was 2042 (rebuild of 2012), but there were a lot of years in between without
#     targets; were those set to 0?
#     - this appears right (nothing was built in those years), but then how was
#       there so much difference between with-thermal and without-thermal in the
#       scenarios I sent to Murray? Did Switch just add early-years offshore wind
#       when new thermal wasn't possible?
#       - yes, without new CC it added extra offshore wind in 2035 & 2040 and
#         extra tracking PV in 2045. There was also some adjustment of sloped
#         vs flat DistPV choices. See compare_build.py.
#   - gist: I was surprised that the model built offshore wind instead of solar or
#     onshore wind in 2030-2040. Dug into it and found a subtle bug in the HECO
#     outlook code that was preventing construction of additional onshore wind or
#     solar in these years but allowing it in 2045. I've fixed that, and the
#     scenarios now end up with a lot more onshore wind and solar in the early
#     years and no offshore wind until 2050 (when it may be a good alternative
#     to rebuilding the 2020 solar when it retires).
#     After fixing this, there are some significant changes in the portfolio
#     that Switch selects:
# - no offshore wind until 2050
# - build about 440 MW of onshore wind in 2025
# - build 700 MW of large solar in 2030-2040 (the 2025 HECO target seems
# close to optimal as-is)
# - build 900 MW of large solar in 2045 (instead of 1300 MW previously)
#   - Building 440 MW of onshore wind in 2025 seems unrealistic. So we
# need to
# think about whether to allow new onshore wind in this scenario, and if so,
# how quickly it could realistically be ramped up. One option would be to shut
# out onshore wind in our main scenario (along with CC) and then do an
# alternative case where it is allowed on some realistic schedule. If we leave
# wind out of the main scenario, then we should consider allowing solar to
# exceed HECO's current plan for 2025. The current HECO solar plan is roughly
# optimal with the 440 MW of new wind, but withtout the wind we likely want
# more solar. **** check this *****
#
#     That gives us potentially 3
#     sensitivity studies: no-CC yes-wind, yes-CC no-wind and yes-CC yes-wind.
#
#     Also, Switch generally now also more renewables in the early years
#     even with the new thermal plant, so the cost-effective renewable level is
#     way above the RPS target all the way to 2045, with or without the new CC
#     plant (*** show production curves ***). The tendency of the CC plant to crowd out
#     renewables is also lower than I reported earlier, giving only about 1.8% savings.
#     (*** refer to curves ***)
#
#
#     After fixing this, we are now preventing Switch from building more large PV
#     than HECO's plan through 2025 (the last year when we have a specific target
#     from them), but only preventing construction of additional wind through 2022
#     (HECO only have a specific amount planned for 2020). It is cost-effective
#     to add a lot more renewables than HECO's solar plan in 2025. Since Switch
#     can't build more solar in 2025, it is now adding 424 MW of onshore  wind in
#     2025. If I treat HECO's 2025 solar plan as a lower bound instead of a fixed
#     target, then Switch instead builds YYYYY MW of onshore wind in 2025 and
#     ZZZZZ MW of large solar.
#     *** check outputs_no_new_thermal_relax_2025_largepv ***
#     This also has interesting effects on costs: even if we stick to HECO's plan
#     for solar in 2025 (and add a lot of wind in 2025), the cost savings from
#     adding CCGT in 2025 have now dropped to 1.8% of total costs in 2020-2054.
#     If we allow construction of solar beyond HECO's plan in 2025, then the gap
#     shrinks to XXX %. So the case for the CC plant is a lot weaker when we
#     allow more renewables.
#     *** check outputs_no_new_thermal_relax_2025_largepv ***
#     On the other hand, Switch now also adds more renewables in the early years
#     even with the new thermal plant, so the cost-effective renewable level is
#     way above the RPS target all the way to 2045, with or without the new CC
#     plant (*** show production curves ***). The tendency of the CC plant to crowd out
#     renewables is also lower than I reported earlier. (*** refer to curves ***)
#
#     , but only applying HECO's plan
#     for onshore or offshore wind through 2022
#
#     In particular, this now
#     includes 424 MW of onshore wind in 2025.
#     That occurs



# EIA-based forecasts, mid-range hydrogen prices, NREL ATB reference technology prices,
# PSIP pre-existing construction, various batteries (LS can provide shifting and reserves),
# 10% DR, no LNG, optimal EV charging, full EV adoption

args = dict(
    # directory to store data in
    inputs_dir='inputs',
    # skip writing capacity factors file if specified (for speed)
    skip_cf = cmd_line_args.skip_cf,
    skip_ev_bids = cmd_line_args.skip_ev_bids,
    # use heat rate curves for all thermal plants
    use_incremental_heat_rates=True,
    # could be 'tiny', 'rps', 'rps_mini' or possibly '2007', '2016test', 'rps_test_45', or 'main'
    # '2020_2025' is two 5-year periods, with 24 days per period, starting in 2020 and 2025
    # "2020_2045_23_2_2" is 5 5-year periods, 6 days per period before 2045, 12 days per period in 2045, 12 h/day
    # time_sample = "2020_2045_23_2_2", # 6 mo/year before 2045
    # time_sample = "k_means_5_12_2",  # representative days, 5-year periods, 12 sample days per period, 2-hour spacing
    # time_sample = "k_means_5_24",  # representative days, 5-year periods, 12 sample days per period, 1-hour spacing
    # time_sample="k_means_5_24_2",  # representative days, 5-year periods, 12 sample days per period, 2-hour spacing
    # time_sample="k_means_5_16+_2",  # representative days, 5-year periods, 16+tough sample days per period, 2-hour spacing
    # time_sample="k_means_235_12+_2",  # representative days, 2/3/5-year periods, 12+tough sample days per period, 2-hour spacing
    # time_sample="k_means_daily_235_12+_2",  # representative days, 2/3/5-year periods, 12+tough sample days per period, 2-hour spacing
    time_sample="k_means_daily_325_2050_12+_2",  # representative days, 3/2/5-year periods through 2054, 12+tough sample days per period, 2-hour spacing
    # subset of load zones to model
    load_zones = ('Oahu',),
    # "hist"=pseudo-historical, "med"="Moved by Passion", "flat"=2015 levels, "PSIP_2016_04"=PSIP 4/16
    # PSIP_2016_12 matches PSIP report but not PSIP modeling, not well documented but seems reasonable
    # in early years and flatter in later years, with no clear justification for that trend.
    # PSIP_2016_12_calib_2018 matches PSIP report but rescales peak and average in all
    # years by a constant value that gets them to match FERC data in 2018
    # IGP_2020_03 is from the Integrated Grid Planning docket, from March 2020,
    # and has been calibrated to account for the difference between HECO's demand-side
    # forecasts and supply-side data reported to FERC and used by Switch.
    load_scenario = "IGP_2020_03",
    # "PSIP_2016_12"=PSIP 12/16; ATB_2018_low, ATB_2018_mid, ATB_2018_high = NREL ATB data; ATB_2018_flat=unchanged after 2018
    tech_scenario='ATB_2020_mid',
    # tech_scen_id='PSIP_2016_12',
    # '1'=low, '2'=high, '3'=reference, 'EIA_ref'=EIA-derived reference level, 'hedged'=2020-2030 prices from Hawaii Gas
    fuel_scenario='AEO_2020_Reference',
    # note: 'unhedged_2016_11_22' is basically the same as 'PSIP_2016_09', but derived directly from EIA and includes various LNG options
    # Blazing a Bold Frontier, Stuck in the Middle, No Burning Desire, Full Adoption,
    # Business as Usual, (omitted or None=none)
    # ev_scenario = 'PSIP 2016-12',  # PSIP scenario
    # ev_scenario = 'Full Adoption',   # 100% by 2045, to match Mayors' commitments
    # ev_scenario = 'EoT 2018',   # 55% by 2045 from HECO Electrification of Transport study (2018)
    ev_scenario = 'IGP 2020',   # from IGP study as of 2020, has lower population than EoT
    ev_charge_profile = 'EoT_2018_avg',  # hourly average of 2030 profile from HECO Electrificaiton of Transport Study
    # should the must_run flag be converted to set minimum commitment for existing plants?
    enable_must_run_before = 2023,
    # list of technologies to exclude (currently CentralFixedPV, because we don't have the logic
    # in place yet to choose between CentralFixedPV and CentralTrackingPV at each site)
    # Lake_Wilson is excluded because we don't have the custom code yet to prevent
    # zero-crossing reserve provision
    exclude_technologies = ('CentralFixedPV', 'Lake_Wilson'), # 'CC_152', 'IC_Barge', 'IC_MCBH', 'IC_Schofield',
    base_financial_year = 2020,
    interest_rate = 0.06,
    discount_rate = 0.03,
    # used to convert nominal costs in the tables to real costs in the base year
    # (generally only shifting by a few years, e.g., 2016 to 2020)
    inflation_rate = 0.020,
    # maximum type of reserves that can be provided by each technology (if restricted);
    # should be a list of tuples of (technology, reserve_type); if not specified, we assume
    # each technology can provide all types of reserves; reserve_type should be "none",
    # "contingency" or "reserve"
    max_reserve_capability=[('Battery_Conting', 'contingency')],
)

# electrolyzer data from centralized current electrolyzer scenario version 3.1 in
# http://www.hydrogen.energy.gov/h2a_prod_studies.html ->
# "Current Central Hydrogen Production from PEM Electrolysis version 3.101.xlsm"
# and
# "Future Central Hydrogen Production from PEM Electrolysis version 3.101.xlsm" (2025)
# (cited by 46719.pdf)
# note: we neglect land costs because they are small and can be recovered later
# TODO: move electrolyzer refurbishment costs from fixed to variable

# liquifier and tank data from http://www.nrel.gov/docs/fy99osti/25106.pdf

# fuel cell data from http://www.nrel.gov/docs/fy10osti/46719.pdf

# note: the article below shows 44% efficiency converting electricity to liquid
# fuels, then 30% efficiency converting to traction (would be similar for electricity),
# so power -> liquid fuel -> power would probably be less efficient than
# power -> hydrogen -> power. On the other hand, it would avoid the fuel cell
# investments and/or could be used to make fuel for air/sea freight, so may be
# worth considering eventually. (solar at $1/W with 28% cf would cost
# https://www.greencarreports.com/news/1113175_electric-cars-win-on-energy-efficiency-vs-hydrogen-gasoline-diesel-analysis
# https://twitter.com/lithiumpowerlpi/status/911003718891454464

inflate_1995 = (1.0+args["inflation_rate"])**(args["base_financial_year"]-1995)
inflate_2007 = (1.0+args["inflation_rate"])**(args["base_financial_year"]-2007)
inflate_2008 = (1.0+args["inflation_rate"])**(args["base_financial_year"]-2008)
h2_lhv_mj_per_kg = 120.21   # from http://hydrogen.pnl.gov/tools/lower-and-higher-heating-values-fuels
h2_mwh_per_kg = h2_lhv_mj_per_kg / 3600     # (3600 MJ/MWh)

current_electrolyzer_kg_per_mwh=1000.0/54.3    # (1000 kWh/1 MWh)(1kg/54.3 kWh)   # TMP_Usage
current_electrolyzer_mw = 50000.0 * (1.0/current_electrolyzer_kg_per_mwh) * (1.0/24.0)   # (kg/day) * (MWh/kg) * (day/h)    # design_cap cell
future_electrolyzer_kg_per_mwh=1000.0/50.2    # TMP_Usage cell
future_electrolyzer_mw = 50000.0 * (1.0/future_electrolyzer_kg_per_mwh) * (1.0/24.0)   # (kg/day) * (MWh/kg) * (day/h)    # design_cap cell

current_hydrogen_args = dict(
    hydrogen_electrolyzer_capital_cost_per_mw=144641663*inflate_2007/current_electrolyzer_mw,        # depr_cap cell
    hydrogen_electrolyzer_fixed_cost_per_mw_year=7134560.0*inflate_2007/current_electrolyzer_mw,         # fixed cell
    hydrogen_electrolyzer_variable_cost_per_kg=0.0,       # they only count electricity as variable cost
    hydrogen_electrolyzer_kg_per_mwh=current_electrolyzer_kg_per_mwh,
    hydrogen_electrolyzer_life_years=40,                      # plant_life cell

    hydrogen_fuel_cell_capital_cost_per_mw=813000*inflate_2008,   # 46719.pdf
    hydrogen_fuel_cell_fixed_cost_per_mw_year=27000*inflate_2008,   # 46719.pdf
    hydrogen_fuel_cell_variable_cost_per_mwh=0.0, # not listed in 46719.pdf; we should estimate a wear-and-tear factor
    hydrogen_fuel_cell_mwh_per_kg=0.53*h2_mwh_per_kg,   # efficiency from 46719.pdf
    hydrogen_fuel_cell_life_years=15,   # 46719.pdf

    hydrogen_liquifier_capital_cost_per_kg_per_hour=inflate_1995*25600,       # 25106.pdf p. 18, for 1500 kg/h plant, approx. 100 MW
    hydrogen_liquifier_fixed_cost_per_kg_hour_year=0.0,   # unknown, assumed low
    hydrogen_liquifier_variable_cost_per_kg=0.0,      # 25106.pdf p. 23 counts tank, equipment and electricity, but those are covered elsewhere
    hydrogen_liquifier_mwh_per_kg=10.0/1000.0,        # middle of 8-12 range from 25106.pdf p. 23
    hydrogen_liquifier_life_years=30,             # unknown, assumed long

    liquid_hydrogen_tank_capital_cost_per_kg=inflate_1995*18,         # 25106.pdf p. 20, for 300000 kg vessel
    liquid_hydrogen_tank_minimum_size_kg=300000,                       # corresponds to price above; cost/kg might be 800/volume^0.3
    liquid_hydrogen_tank_life_years=40,                       # unknown, assumed long
)

# future hydrogen costs
future_hydrogen_args = current_hydrogen_args.copy()
future_hydrogen_args.update(
    hydrogen_electrolyzer_capital_cost_per_mw=58369966*inflate_2007/future_electrolyzer_mw,        # depr_cap cell
    hydrogen_electrolyzer_fixed_cost_per_mw_year=3560447*inflate_2007/future_electrolyzer_mw,         # fixed cell
    hydrogen_electrolyzer_variable_cost_per_kg=0.0,       # they only count electricity as variable cost
    hydrogen_electrolyzer_kg_per_mwh=future_electrolyzer_kg_per_mwh,
    hydrogen_electrolyzer_life_years=40,                      # plant_life cell

    # table 5, p. 13 of 46719.pdf, low-cost
    # ('The value of $434/kW for the low-cost case is consistent with projected values for stationary fuel cells')
    hydrogen_fuel_cell_capital_cost_per_mw=434000*inflate_2008,
    hydrogen_fuel_cell_fixed_cost_per_mw_year=20000*inflate_2008,
    hydrogen_fuel_cell_variable_cost_per_mwh=0.0, # not listed in 46719.pdf; we should estimate a wear-and-tear factor
    hydrogen_fuel_cell_mwh_per_kg=0.58*h2_mwh_per_kg,
    hydrogen_fuel_cell_life_years=26,
)

mid_hydrogen_args = {
    key: 0.5 * (current_hydrogen_args[key] + future_hydrogen_args[key])
    for key in future_hydrogen_args.keys()
}
args.update(future_hydrogen_args)

args.update(
    pumped_hydro_headers=[
        'ph_project_id', 'ph_load_zone', 'ph_capital_cost_per_mw',
        'ph_project_life', 'ph_fixed_om_percent',
        'ph_efficiency', 'ph_inflow_mw', 'ph_max_capacity_mw'],
    pumped_hydro_projects=[
        ['Lake_Wilson', 'Oahu', 2800*1000+35e6/150, 50, 0.015, 0.77, 10, 150],
    ]
)

# TODO: move this into the data import system
args.update(
    rps_targets = {2015: 0.15, 2020: 0.30, 2030: 0.40, 2040: 0.70, 2045: 1.00}
)
rps_2030 = {2020: 0.4, 2025: 0.7, 2030: 1.0}

def write_inputs(args, **alt_args):
    all_args = args.copy()
    all_args.update(alt_args)
    scenario_data.write_tables(all_args)

# write regular scenario
write_inputs(args)
write_inputs(args, inputs_dir='inputs_heco')

# tiny scenario for testing
write_inputs(args, inputs_dir='inputs_tiny', time_sample='tiny')

# small scenario for debugging
write_inputs(args, inputs_dir='inputs_small', time_sample='small_2050')

# non-worst-day (could be used to experiment with weighting, but wasn't)
# write_inputs(
#     args,
#     inputs_dir='inputs_non_worst',
#     time_sample=args['time_sample'].replace('+', '')
# )

# annual model for post-optimization evaluation (may be too big to solve)
# (gets too big to solve if run hourly?)
write_inputs(
    args,
    inputs_dir='inputs_annual',
    time_sample=args['time_sample'].replace('_325_', '_1_') # .replace('_2', '')
)
write_inputs(
    args,
    inputs_dir='inputs_annual_heco',
    time_sample=args['time_sample'].replace('_325_', '_1_') # .replace('_2', '')
)
# short annual model for post-optimization evaluation (may be too big to solve)
write_inputs(
    args,
    inputs_dir='inputs_2019_2022',
    time_sample=args['time_sample'].replace('_325_2050_', '_2019_2022_')
)

# shift Kahe 5 and 6 retirement from 2045 to 2028 for HECO plan
import os
import pandas as pd
for inputs_dir in ['inputs', 'inputs_annual']:
    df = pd.read_csv(os.path.join(inputs_dir, 'generation_projects_info.csv'))
    df.loc[(df['gen_tech']=='Kahe_5') | (df['gen_tech']=='Kahe_6'), 'gen_max_age'] \
        += (2028 - 2045)
    df.to_csv(os.path.join(inputs_dir+'_heco', 'generation_projects_info.csv'), index=False)
print("Need to somehow remove existing Pearl City Peninsula Solar Park from inputs_heco and inputs_heco_annual")
