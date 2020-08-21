# Introduction

This repository contains data used to construct "Ulupono Scenario 2.1" used in
Hawaii PUC docket 2018-0088 on Performance Based Regulation. This scenario was
created by first choosing an optimal long-term design for the power system in
5-year steps (using data in the `inputs` directory), then evaluating the
performance of the model in one-year steps (using data in the `inputs_annual`
directory). Both of these optimization problems were solved using a pre-release
version of Switch 2.0.6. Results from these two steps are in the `outputs` and
`outputs_annual` directories. These became "Ulupono #2.1" scenario in the RIST
workbook used in this docket.

The sections below describe how to install the input data and results on your
computer, install the version of Switch used to solve this model (only needed if
you want to modify and re-solve the model), solve the model, and inspect the
results. They also show how to inspect the data online if you prefer not to copy
it to your computer.

Please contact Matthias Fripp <mfripp@hawaii.edu> if you have any questions
about using the data or model or interpreting the results.

# 1. Install or view Scenario 2.1 data

Follow the steps below to install a copy of the Scenario 2.1 data on your computer
(optional).

- Download the data from
  https://github.com/switch-hawaii/ulupono_scenario_2.1/archive/2020-08-20.zip
  (256 MB).
- Unzip the downloaded file. This will produce a folder containing all the input
  and output data for Scenario 2.1 (1.8 GB).  
- Rename the folder if desired (e.g., "ulupono_scenario_2.1") and move it to a
  convenient location.
- As an alternative, if you are familiar with `git`, you can use it to retrieve
  the data from https://github.com/switch-hawaii/ulupono_scenario_2.1.git. Then
  checkout the `2020-08-20` tag.

If you don't want to download the data, you can view it directly at
https://github.com/switch-hawaii/ulupono_scenario_2.1/tree/2020-08-20 instead.

All the inputs to construct the scenario are in the `inputs` and `inputs_annual`
directories. Configuration information is in `modules.txt` and `options.txt`.
(See http://switch-model.org for more information on configuring and using
Switch.) There is also some data embedded in the Switch modules used for this
model (e.g., `tech_group_targets_definite` in
`switch_model.hawaii.heco_outlook_2020_08` and
`switch_model.hawaii.heco_plan_2020_08`). See section 3 for instructions on how
to view or install the version of Switch used for Scenario 2.1.

The files in the `inputs` and `inputs_annual` directories show the data used to
run Switch. These were created by extracting the relevant data from the
Switch-Hawaii data warehouse using the `get_scenario_data.py` script in the
`ulupono_scenario_2.1` directory. The data sources used to prepare these inputs
are described in `Ulupono Scenario 2.1 Documentation 2020-08-18.pdf`.

If you want to dive deeper, all the source files and code used to build the data
warehouse are published in the https://github.com/switch-hawaii/data repository.
(This is updated periodically; the version used for Scenario 2.1 is at
https://github.com/switch-hawaii/data/tree/4888f3483856bde1bfa3ab21b44988395f7af643.)
Click on the "Code" button to download a copy of the data and code. This
repository includes spreadsheets with notes about the origin of data, GIS
shapefiles and text files explaining the steps to take to download upstream
data. Locations of most information should be fairly obvious, but some extra
data (e.g., sales forecasts) are stored in 'PSIP 2016-12 ATB 2020 generator
data.xlsx' in the `Generator Info` directory.

The Switch power system planning model was used to create an optimal plan for
the power system based on the assumptions in the `inputs` and `inputs_annual`
directories (and some built into the Switch model code). This process is
discussed in section 4 below, and the data describing the resulting plan are
discussed in section 5.

# 2. Install Python and a solver

The steps in this section are only needed if you want to modify and re-solve the
model.

Install Python 3.7 or later. Earlier versions may work but have not been tested.
[Miniconda](https://docs.conda.io/en/latest/miniconda.html) is a good,
cross-platform installer. Or you can use the [standard Python
installer](https://www.python.org/downloads/). Either of these should include
the `pip` package manager for Python.

In addition to Python and the Switch code (below), you will need a
commercial-grade solver to actually solve the optimization model. CPLEX and
Gurobi work well. Open-source solvers such as glpk or cbc are not fast enough
for this model.

Be sure to update the lines for `--solver` and `--solver-options-string` in
`ulupono_scenario_2.1/options.txt` to match the solver you are using.

# 3. Install or view Switch model code

This model was solved using a pre-release version of Switch 2.0.6. You can find
the version used for this study at
https://github.com/switch-model/switch/tree/ea6a7b5593b33568c4f394d0c4b618b50f3d42cf.
If you do not want to install and re-run the model, you can just view the code
at that URL.

If you want to install Switch itself (e.g., to re-solve the model), proceed as
follows:

1. Launch a Terminal window or Anaconda prompt
2. Type this command (all on one line):
`pip install https://github.com/switch-model/switch/archive/ea6a7b5593b33568c4f394d0c4b618b50f3d42cf.zip`

This will install the version of Switch used for this study, along with other
packages that it requires (but not a commercial-grade solver). Please contact
Matthias Fripp <mfripp@hawaii.edu> if you have questions about installing
Switch.

# 4. Solve the model

This step is only needed if you have modified the inputs. Otherwise, you can
inspect the already-solved outputs as described in the next section.

You can create and evaluate Scenario 2.1 as follows:

- launch a Terminal window or Anaconda Command prompt
- use the `cd` command to navigate to the `ulupono_scenario_2.1` directory
- run this command: `switch solve`
  - this will solve the main optimization stage and write the results to the
    `outputs` directory
  - you can run `switch solve --help` to see more options
  - this uses the modules listed in `modules.txt` and configuration options
    listed in `options.txt` in the `ulupono_scenario_2.1` directory
- run this command: `python interpolate_construction_plan.py`
  - this will move installation of batteries and utility-scale solar to earlier
    years to smooth out the installation plan (the new plan is saved in
    `inputs_annual/*_modified.csv`)
- run this command: `cat outputs/BuildPumpedHydroMW.csv` (Mac/Linux) or
  `type outputs/BuildPumpedHydroMW.csv` (Windows)
  - make note of the year when pumped hydro is built and the amount built
- run this command (all on one line): `switch solve --inputs-dir inputs_annual --outputs-dir outputs_annual --ph-mw 150 --ph-year 2030 --input-alias gen_build_predetermined.csv=gen_build_predetermined_adjusted.csv  generation_projects_info.csv=generation_projects_info_adjusted.csv --exclude-module switch_model.hawaii.heco_outlook_2020_08`
  - be sure to update the `--ph-mw` and `--ph-year` settings to show the correct
    amount and date; use `--ph-mw 0 --ph-year 2020` if no pumped hydro is built
  - this will save the annual results in `outputs_annual`

The HECO Plan can be evaluated by running the following commands (each should
be typed on a single line):

`switch solve --psip-force --exclude-module no_new_thermal_capacity switch_model.hawaii.heco_outlook_2020_08 --include-module switch_model.hawaii.heco_plan_2020_08 --inputs-dir inputs_heco --outputs-dir outputs_heco`

`python interpolate_construction_plan.py --heco-plan`

`switch solve --inputs-dir inputs_annual_heco --outputs-dir outputs_annual_heco --ph-mw 0 --ph-year 2045 --input-alias gen_build_predetermined.csv=gen_build_predetermined_adjusted.csv generation_projects_info.csv=generation_projects_info_adjusted.csv --exclude-modules no_new_thermal_capacity switch_model.hawaii.heco_outlook_2020_08`

Settings for the first-stage optimization for other scenarios are listed in
`scenarios.txt`. They can be pasted on the command line after `switch solve`
before pressing "enter". You may omit the `--scenario-name` setting.

Note that re-solving the model may produce different results from the ones shown
in the repository. This is because the model is usually solved only to within
0.5% of perfect optimality, and a variety of solutions are possible within this
limit. Solutions may differ depending on the brand or version of the solver you
use, solver options settings, the version of Pyomo (used by Switch), or
operating system. However, all the solutions should be within 0.5% of each other
in total cost. The results shown here were produced using the CPLEX solver,
version 12.6.0.0
(`~/Applications/IBM/ILOG/CPLEX_Studio126/cplex/bin/x86-64_osx/cplexamp`) with
settings shown in options.txt, on MacOS 10.14.6, with Pyomo version 5.6.6 and
Pyutilib version 5.7.1 (`pip install pyomo==5.6.6 pyutilib==5.7.1`).

# 5. Inspect results

Ulupono Scenario 2.1 is defined by the outputs of the optimization steps listed
above. These can be found at http://github.com/switch-hawaii/ulupono_scenario_2.1
or in the `ulupono_scenario_2.1` directory that you created on your computer, as
described above.

All results from the main optimization stage (with investment decisions in 2020,
2023, 2025, 2030, 2035, 2040, 2045 and 2050) are in `outputs`. All results from
the annual evaluation are in `outputs_annual`. The files with mixed capital and
lowercase names (e.g., `BuildGen.csv`) are individual decisions made by the
model. The files with lowercase names and underscores (e.g.,
`capacity_by_technology.csv`) are summary files. `total_cost.txt` shows the NPV
of total costs during the whole study.

Here are some useful tables:

- `capacity_by_technology.csv`: summary of capacity in place each year
- `production_by_technology.csv`: summary of energy sources used each year
- `annual_details_by_tech.csv`: data used for RIST workbook in Hawaii PUC docket
  2018-0088
- `gen_dispatch.csv`: details on dispatch of individual standard generators
- `PumpedHydroProjGenerateMW.csv`: details on dispatch of pumped hydro (if any)

Please contact Matthias Fripp <mfripp@hawaii.edu> if you have questions about
the outputs or reproducing this work.
