# glicko2.py

import math

class Player:
    def __init__(self, rating=1500, rd=350, vol=0.06):
        self._rating = rating
        self._rd = rd
        self._vol = vol
        self._tau = 0.5  # волатильность — можно адаптировать под ваш PvP

    def getRating(self):
        return self._rating

    def getRd(self):
        return self._rd

    def pre_rating_period(self):
        c = 34.6  # рост неопределенности с течением времени (настройка decay)
        self._rd = min(math.sqrt(self._rd ** 2 + c ** 2), 350)

    def _g(self, rd):
        return 1 / math.sqrt(1 + 3 * (rd ** 2) / (math.pi ** 2))

    def _E(self, rating, opp_rating, opp_rd):
        return 1 / (1 + math.exp(-self._g(opp_rd) * (rating - opp_rating)))

    def update_player(self, rating_list, RD_list, outcome_list):
        mu = (self._rating - 1500) / 173.7178
        phi = self._rd / 173.7178

        opp_mu = [(r - 1500) / 173.7178 for r in rating_list]
        opp_phi = [rd / 173.7178 for rd in RD_list]

        g_list = [1 / math.sqrt(1 + 3 * (phi_j ** 2) / (math.pi ** 2)) for phi_j in opp_phi]
        E_list = [1 / (1 + math.exp(-g * (mu - mu_j))) for g, mu_j in zip(g_list, opp_mu)]

        # Шаг 2: вычисляем дисперсию
        v_inv = sum((g ** 2) * E * (1 - E) for g, E in zip(g_list, E_list))
        v = 1 / v_inv

        # Шаг 3: вычисляем дельту
        delta = v * sum(g * (s - E) for g, s, E in zip(g_list, outcome_list, E_list))

        # Шаг 4: пропустим обновление волатильности (для упрощения)

        # Шаг 5: phi*
        phi_star = math.sqrt(phi ** 2 + self._vol ** 2)

        # Шаг 6: новое значение phi
        phi_new = 1 / math.sqrt((1 / (phi_star ** 2)) + (1 / v))

        # Шаг 7: новое значение mu
        mu_new = mu + (phi_new ** 2) * sum(g * (s - E) for g, s, E in zip(g_list, outcome_list, E_list))

        # Шаг 8: обратно к рейтингу
        self._rating = 173.7178 * mu_new + 1500
        self._rd = 173.7178 * phi_new
