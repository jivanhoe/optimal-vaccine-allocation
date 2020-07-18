import datetime as dt
from copy import deepcopy
from typing import List, Dict, Union, Optional

import pandas as pd

from data_utils.constants import *
from models.mortality_rate_estimator import MortalityRateEstimator


def get_population_by_state_and_risk_class(pop_df: pd.DataFrame) -> np.ndarray:
    states = pop_df["state"].unique()
    population = np.zeros((len(states), len(RISK_CLASSES)))
    for j, state in enumerate(states):
        for k, risk_class in enumerate(RISK_CLASSES):
            population[j, k] = pop_df[
                (pop_df["min_age"] >= risk_class["min_age"])
                & (pop_df["max_age"] <= risk_class["max_age"])
                & (pop_df["state"] == state)
            ]["population"].sum()
    return population


def get_policy_response_by_state_and_timestep(params_df: pd.DataFrame, start_date: dt.datetime) -> np.ndarray:
    policy_response = np.zeros((N_REGIONS, N_TIMESTEPS))
    t = np.arange(N_TIMESTEPS) * DAYS_PER_TIMESTEP
    for j, (state, params) in enumerate(params_df.iterrows()):
        offset = (start_date - params["start_date"]).days * DAYS_PER_TIMESTEP
        lockdown_curve = 2 / np.pi * np.arctan(
            -(t + offset - params["intervention_time"]) * params["intervention_rate"] / 20
        )
        reopening_curve = params["jump_magnitude"] * np.exp(
            -((t + offset - params["jump_time"]) / params["jump_decay"]) ** 2 / 2
        )
        policy_response[j, :] = 1 + lockdown_curve + reopening_curve
    return policy_response


def get_hospitalization_rate_by_risk_class(cdc_df: pd.DataFrame) -> np.ndarray:
    hospitalization_rate = np.zeros(N_RISK_CLASSES)
    for k, risk_class in enumerate(RISK_CLASSES):
        cases, hospitalizations = cdc_df[
            (cdc_df["min_age"] >= risk_class["min_age"])
            & (cdc_df["max_age"] <= risk_class["max_age"])
        ][["cases", "hospitalizations"]].sum()
        hospitalization_rate[k] = hospitalizations / cases
    return hospitalization_rate


def get_baseline_mortality_rate_estimates(cdc_df: pd.DataFrame) -> np.ndarray:
    baseline_mortality_rate = np.zeros(N_RISK_CLASSES)
    for k, risk_class in enumerate(RISK_CLASSES):
        cases, deaths = cdc_df[
            (cdc_df["min_age"] >= risk_class["min_age"])
            & (cdc_df["max_age"] <= risk_class["max_age"])
        ][["cases", "deaths"]].sum()
        baseline_mortality_rate[k] = deaths / cases
    return baseline_mortality_rate


def get_mortality_rate_estimates(
        pop_df: pd.DataFrame,
        cdc_df: pd.DataFrame,
        predictions_df: pd.DataFrame,
        start_date: dt.datetime
) -> np.ndarray:
    population = get_population_by_state_and_risk_class(pop_df=pop_df)
    baseline_mortality_rate = get_baseline_mortality_rate_estimates(cdc_df=cdc_df)
    states = pop_df["states"].unique()
    mortality_rate = np.ndarray((N_REGIONS, N_RISK_CLASSES, N_TIMESTEPS))
    for j, state in enumerate(states):
        cases, deaths = predictions_df[
            (predictions_df["date"] >= start_date)
            & (predictions_df["state"] == state)
        ][["exposed", "deceased"]].diff().dropna()
        mortality_rate[j, :, :] = MortalityRateEstimator(
            cases=cases,
            deaths=deaths,
            baseline_mortality_rate=baseline_mortality_rate,
            population=population[j, :],
            max_pct_change=MAX_PCT_CHANGE,
            max_pct_population_deviation=MAX_PCT_CHANGE,
            n_timesteps_per_estimate=N_TIMESTEPS_PER_ESTIMATE
        ).solve()[0]
    return mortality_rate


def get_initial_conditions(
        pop_df: pd.DataFrame,
        predictions_df: pd.DataFrame,
        start_date: dt.datetime
) -> Dict[str, np.ndarray]:

    # Get population by state and risk class
    population = get_population_by_state_and_risk_class(pop_df=pop_df)

    # Get estimated susceptible, exposed and infectious for start date
    initial_default = np.zeros(population.shape)
    initial_susceptible = deepcopy(initial_default)
    initial_exposed = deepcopy(initial_default)
    initial_infectious = deepcopy(initial_default)
    initial_conditions_df = predictions_df[
        predictions_df["date"] == start_date
        ].sort_values("state")[["susceptible", "exposed", "infected"]]
    for j, (_, state) in enumerate(initial_conditions_df.iterrows()):
        pop_proportions = population[j, :] / population[j, :].sum()
        initial_susceptible[j, :] = state["susceptible"] * pop_proportions
        initial_exposed[j, :] = state["exposed"] * pop_proportions
        initial_infectious[j, :] = state["infectious"] * pop_proportions

    # Return dictionary of all initial conditions
    return dict(
        initial_susceptible=initial_susceptible,
        initial_exposed=initial_exposed,
        initial_infectious=initial_infectious,
        initial_hospitalized_dying=initial_default,
        initial_hospitalized_recovering=initial_default,
        initial_quarantined_dying=initial_default,
        initial_quarantined_recovering=initial_default,
        initial_undetected_dying=initial_default,
        initial_undetected_recovering=initial_default,
        initial_recovered=initial_default,
        population=population
    )


def get_delphi_params(
        pop_df: pd.DataFrame,
        cdc_df: pd.DataFrame,
        params_df: pd.DataFrame,
        predictions_df: pd.DataFrame,
        start_date: dt.datetime
) -> Dict[str, Union[float, np.ndarray]]:

    # Get policy response by state and timestep
    policy_response = get_policy_response_by_state_and_timestep(
        params_df=params_df,
        start_date=start_date
    )

    # Get estimated hospitalization rates from CDC data
    hospitalization_rate = get_hospitalization_rate_by_risk_class(cdc_df=cdc_df)
    hospitalization_rate = hospitalization_rate[None, :, None]

    # Get mortality rate estimates
    mortality_rate = get_mortality_rate_estimates(
        pop_df=pop_df,
        cdc_df=cdc_df,
        predictions_df=predictions_df,
        start_date=start_date
    )

    # Convert median times to rates
    progression_rate = np.log(2) / MEDIAN_PROGRESSION_TIME
    detection_rate = np.log(2) / MEDIAN_DETECTION_TIME
    hospitalized_death_rate = np.log(2) / MEDIAN_HOSPITALIZED_DEATH_TIME
    unhospitalized_death_rate = np.log(2) / MEDIAN_UNHOSPITALIZED_DEATH_TIME
    hospitalized_recovery_rate = np.log(2) / MEDIAN_HOSPITALIZED_RECOVERY_TIME
    unhospitalized_recovery_rate = np.log(2) / MEDIAN_UNHOSPITALIZED_DEATH_TIME

    return dict(
        infection_rate=np.array(params_df["infection_rate"]),
        policy_response=policy_response,
        progression_rate=progression_rate,
        detection_rate=detection_rate,
        ihd_transition_rate=detection_rate * DETECTION_PROBABILITY * hospitalization_rate * mortality_rate,
        ihr_transition_rate=detection_rate * DETECTION_PROBABILITY * hospitalization_rate * (1 - mortality_rate),
        iqd_transition_rate=detection_rate * DETECTION_PROBABILITY * (1 - hospitalization_rate) * mortality_rate,
        iqr_transition_rate=detection_rate * DETECTION_PROBABILITY * (1 - hospitalization_rate) * (1 - mortality_rate),
        iud_transition_rate=detection_rate * (1 - DETECTION_PROBABILITY) * hospitalization_rate,
        iur_transition_rate=detection_rate * (1 - DETECTION_PROBABILITY) * (1 - hospitalization_rate),
        hospitalized_death_rate=hospitalized_death_rate,
        unhospitalized_death_rate=unhospitalized_death_rate,
        hospitalized_recovery_rate=hospitalized_recovery_rate,
        unhospitalized_recovery_rate=unhospitalized_recovery_rate,
        mortality_rate=mortality_rate,
        days_per_timestep=DAYS_PER_TIMESTEP
    )


def get_vaccine_params(
        total_pop: float,
        vaccine_effectiveness: float,
        vaccine_budget_pct: float,
        max_allocation_pct: float,
        min_allocation_pct: float,
        max_decrease_pct: float,
        max_increase_pct: float,
        max_total_capacity_pct: Optional[float] = None,
        optimize_capacity: bool = False,
        excluded_risk_classes: Optional[List[int]] = None
) -> Dict[str, Union[float, np.ndarray]]:
    return dict(
        vaccine_effectiveness=vaccine_effectiveness,
        vaccine_budget=np.array([total_pop * vaccine_budget_pct for _ in range(N_TIMESTEPS)]),
        max_total_capacity=(max_total_capacity_pct if max_total_capacity_pct else vaccine_budget_pct) * total_pop,
        max_allocation_pct=max_allocation_pct,
        min_allocation_pct=min_allocation_pct,
        max_decrease_pct=max_decrease_pct,
        max_increase_pct=max_increase_pct,
        optimize_capacity=optimize_capacity,
        excluded_risk_classes=np.array(excluded_risk_classes) if excluded_risk_classes else np.array([]).astype(int),
    )
