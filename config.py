# config.py

# Спрос по годам (Базовый общий и критический)
DEMAND_BASE = {
    2035: {'total': 100, 'critical': 80},
    2036: {'total': 140, 'critical': 105},
    2037: {'total': 190, 'critical': 135},
    2038: {'total': 250, 'critical': 170},
    2039: {'total': 320, 'critical': 210},
    2040: {'total': 390, 'critical': 250},
}

# Каналы снабжения[cite: 3]
CHANNELS = {
    'Earth-Core': {'cap': 190, 'var_cost': 6.2, 'res_cost': 0.45, 'top_rate': 0.70},
    'Earth-Flex': {'cap': 110, 'var_cost': 8.9, 'res_cost': 0.15, 'top_rate': 0.0},
    'Earth-New':  {'cap': 130, 'var_cost': 7.1, 'res_cost': 0.30, 'top_rate': 0.50, 'capex': 360},
    'Lunar-ISRU': {'cap': 120, 'var_cost': 3.0, 'res_cost': 0.0,  'top_rate': 0.0, 'capex': 1250, 'opex': 70},
    'Emergency':  {'cap': 80,  'var_cost': 13.8, 'res_cost': 0.35, 'top_rate': 0.0},
}

# Хранилище: базовое и опцион ZBO-модернизации[cite: 3]
STORAGE_BASE = {'capacity': 70, 'loss_rate': 0.045, 'cost_per_ton': 0.72}
STORAGE_ZBO = {'capacity': 120, 'loss_rate': 0.012, 'cost_per_ton': 0.72, 'capex': 180, 'opex': 12}

DISCOUNT_RATE = 0.10 # Ставка дисконтирования