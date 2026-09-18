# math_core.py
import pandas as pd
from config import DEMAND_BASE, CHANNELS, STORAGE_BASE, STORAGE_ZBO, DISCOUNT_RATE

class FuelSpaceContour:
    def __init__(self, scenario="standard"):
        self.scenario = scenario

    def apply_stress(self, year, demand, ch_params):
        if self.scenario == "stress" and year >= 2038:
            demand['total'] *= 1.15
            demand['critical'] *= 1.15
            ch_params['Earth-Core']['var_cost'] *= 1.25
            ch_params['Earth-Flex']['var_cost'] *= 1.25
        return demand, ch_params

    def apply_geopolitical_risk(self, year, ch_params, geo_settings):
        if not geo_settings.get('active', False): return ch_params
        if year >= geo_settings.get('start_year', 2040):
            target_channel = geo_settings.get('channel')
            multiplier = geo_settings.get('price_multiplier', 1.0)
            if target_channel in ch_params:
                ch_params[target_channel]['var_cost'] *= multiplier
        return ch_params

    def run_simulation(self, strategy, inv_decisions, geo_settings=None, end_year=2040, demand_mult=1.0):
        if geo_settings is None: geo_settings = {'active': False}
        results = []
        current_inventory = 10 
        cumulative_capex = 0
        capex_2037 = 0 
        total_npv = 0
        
        isru_active = inv_decisions.get('Lunar-ISRU', False)
        zbo_active = inv_decisions.get('ZBO', False)
        earth_new_active = inv_decisions.get('Earth-New', False)

        for year in range(2035, end_year + 1):
            if year not in strategy: continue
            
            # Экстраполяция спроса для расчёта на перспективу (>2040)[cite: 3]
            if year <= 2040:
                demand = {k: v * demand_mult for k, v in DEMAND_BASE[year].items()}
            else:
                growth = 1.10 ** (year - 2040) # Условный рост 10% в год за горизонтом[cite: 3]
                demand = {k: v * growth * demand_mult for k, v in DEMAND_BASE[2040].items()}
                
            ch_params = {k: v.copy() for k, v in CHANNELS.items()}
            demand, ch_params = self.apply_stress(year, demand, ch_params)
            ch_params = self.apply_geopolitical_risk(year, ch_params, geo_settings)
            
            supply_plan = strategy[year]
            storage_params = STORAGE_ZBO if (zbo_active and year >= 2036) else STORAGE_BASE

            total_supply = sum(plan.get('ordered', 0) * (0.55 if self.scenario == "stress" and ch_name == 'Lunar-ISRU' and year == 2038 else (0.75 if self.scenario == "stress" and ch_name == 'Lunar-ISRU' and year == 2039 else 1)) for ch_name, plan in supply_plan.items())

            losses = total_supply * storage_params['loss_rate']
            available_fuel = current_inventory + total_supply - losses
            
            supplied_total = min(available_fuel, demand['total'])
            supplied_critical = min(available_fuel, demand['critical'])
            end_inventory = min(available_fuel - supplied_total, storage_params['capacity'])
            
            required_reserve = demand['total'] * 45 / 365
            
            capex_year = 0
            opex_year = 0
            costs = {'variable': 0, 'reserve': 0, 'storage': 0}
            
            if year == 2036 and zbo_active: capex_year += STORAGE_ZBO['capex']
            if year == 2038 and isru_active: capex_year += CHANNELS['Lunar-ISRU']['capex']
            if year == 2037 and earth_new_active: capex_year += CHANNELS['Earth-New']['capex']
            if isru_active and year >= 2038: opex_year += CHANNELS['Lunar-ISRU']['opex']
            if zbo_active and year >= 2036: opex_year += STORAGE_ZBO['opex']

            cumulative_capex += capex_year
            if year <= 2037: capex_2037 += capex_year

            for ch_name, plan in supply_plan.items():
                params = ch_params.get(ch_name, {})
                if not params: continue
                costs['reserve'] += plan.get('reserved', 0) * params.get('res_cost', 0)
                paid_volume = max(plan.get('ordered', 0), plan.get('reserved', 0) * params.get('top_rate', 0))
                costs['variable'] += paid_volume * params.get('var_cost', 0)

            avg_inventory = (current_inventory + end_inventory) / 2
            costs['storage'] += avg_inventory * storage_params['cost_per_ton']
            
            yearly_total_cost = sum(costs.values()) + capex_year + opex_year
            discount_factor = (1 + DISCOUNT_RATE) ** (year - 2035)
            total_npv += yearly_total_cost / discount_factor

            crit_pct = supplied_critical / demand['critical']
            tot_pct = supplied_total / demand['total']
            is_valid = crit_pct >= 0.99 and tot_pct >= 0.97 and end_inventory >= required_reserve
            
            results.append({
                'Год': year, 'Затраты (млн)': round(yearly_total_cost, 2),
                'CAPEX': capex_year, 'NPV нарастающим': round(total_npv, 2),
                'Остаток': round(end_inventory, 2), 'Норма (45дн)': round(required_reserve, 2),
                'Крит. сервис (%)': round(crit_pct * 100, 1), 'План валиден': is_valid
            })
            current_inventory = end_inventory

        return pd.DataFrame(results), cumulative_capex, capex_2037, total_npv