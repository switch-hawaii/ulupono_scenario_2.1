from pyomo.environ import Constraint

def define_arguments(argparser):
    argparser.add_argument('--onshore-wind-limit', type=float, default=323.0,
        help="""
            Maximum number of MW of onshore wind that can be operational in
            any period. Default is 323, which is equal to Kahuku (30) +
            Kawailoa (69) + Na Pua Makani (24) + 200 more.
        """
    )

def define_components(m):
    m.Limit_New_Wind = Constraint(
        m.PERIODS,
        rule=lambda m, p: sum(
            m.GenCapacity[g, p]
            for g in m.GENS_IN_PERIOD[p]
            if m.gen_tech[g] == 'OnshoreWind'
        ) <= m.options.onshore_wind_limit
    )
    print('Restricting onshore wind to total of {} MW'.format(m.options.onshore_wind_limit))
