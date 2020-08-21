from pyomo.environ import Constraint

def define_components(m):
    m.No_New_Thermal = Constraint(
        m.FUEL_BASED_GENS, m.PERIODS,
        rule=lambda m, g, p:
             (m.BuildGen[g, p] == 0)
             if (g, p) in m.BuildGen
             else Constraint.Skip
    )
