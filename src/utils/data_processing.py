from typing import List, Callable, Tuple, Optional

import numpy as np
import pandas as pd


def process_pop_data(
        pop_df: pd.DataFrame,
        age_cutoffs: List[float]
) -> np.ndarray:
    age_cutoffs.insert(0, 0)
    age_cutoffs.append(np.inf)
    num_classes = len(age_cutoffs) - 1

    pop = np.zeros((len(pop_df), num_classes))
    for i in range(num_classes):
        pop[:, i] = pop_df[
            [age for age in pop_df.columns if (int(age) >= age_cutoffs[i]) and (int(age) < age_cutoffs[i+1])]
        ].sum(1)

    return pop


def process_density_data(
        pop_df: pd.DataFrame,
        land_area_df: pd.DataFrame
) -> np.ndarray:
    df = land_area_df.merge(
        pop_df.sum(1).rename("total_pop"),
        left_index=True,
        right_index=True,
        how="inner"
    )
    return np.array(df["total_pop"] / df["land_area"])


def process_census_data(
        pop_data_path: str,
        land_area_data_path: str,
        age_cutoffs: List[float],
        rep_factor_model: Callable[[np.ndarray], np.ndarray],
        groupby_state: bool
) -> Tuple[np.ndarray, np.ndarray]:
    pop_df = pd.read_csv(pop_data_path, index_col=[0, 1]).sort_index()
    land_area_df = pd.read_csv(land_area_data_path, index_col=[0, 1]).sort_index()
    if groupby_state:
        pop_df = pop_df.reset_index().groupby("state").sum()
        land_area_df = land_area_df.reset_index().groupby("state").sum()

    pop = process_pop_data(
        pop_df=pop_df,
        age_cutoffs=age_cutoffs
    )
    density = process_density_data(
        pop_df=pop_df,
        land_area_df=land_area_df
    )
    assert len(pop) == len(density), "Inconsistent population and land area data."

    return pop, rep_factor_model(density)


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-x))


def toy_rep_factor_model(
        density: np.ndarray,
        min_rep_factor: float,
        max_rep_factor: float
) -> np.ndarray:
    normalized_density = density - np.mean(density) / np.std(density)
    rep_factor = max_rep_factor * sigmoid(normalized_density)
    rep_factor = rep_factor + min_rep_factor - np.min(rep_factor)
    return rep_factor


def set_budget_from_pop(
        pop: np.ndarray,
        immunized_pop: np.ndarray,
        active_cases: np.ndarray,
        budget_pct: float = 0.1
) -> np.ndarray:
    return np.ones(int(np.round(1 / budget_pct))) * (pop - immunized_pop - active_cases).sum() * budget_pct


def get_toy_data_from_census_data(
        pop_data_path: str,
        land_area_data_path: str,
        pct_immune: float = 5e-2,
        pct_active_cases: float = 5e-3,
        pct_budget: float = 1e-1,
        min_rep_factor: float = 0.7,
        max_rep_factor: float = 1.5,
        age_cutoffs: Tuple[float] = (50, 70),
        morbidity_rate: Tuple[float] = (2e-3, 1e-2, 1e-1),
        unit: float = 1e6,
        groupby_state: bool = False,
        max_regions: Optional[int] = None
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    pop, rep_factor = process_census_data(
        pop_data_path=pop_data_path,
        land_area_data_path=land_area_data_path,
        age_cutoffs=list(age_cutoffs),
        groupby_state=groupby_state,
        rep_factor_model=lambda density: toy_rep_factor_model(
            density=density,
            min_rep_factor=min_rep_factor,
            max_rep_factor=max_rep_factor
        )
    )
    pop /= unit
    if max_regions:
        pop = pop[:max_regions]
        rep_factor = rep_factor[:max_regions]
    immunized_pop = pop * pct_immune
    active_cases = pop * pct_active_cases
    budget = np.ones(int(np.round(1 / pct_budget))) * (pop - immunized_pop - active_cases).sum() * pct_budget
    budget[0] = 0
    morbidity_rate = np.tile(morbidity_rate, (pop.shape[0], 1))
    return pop, immunized_pop, active_cases, rep_factor, morbidity_rate, budget


def load_data(data_dir: str, budget_pct: float = 0.1) -> List[np.ndarray]:
    data = []
    for file_name in ["pop", "immunized_pop", "active_cases", "rep_factor", "morbidity_rate"]:
        data.append(np.array(pd.read_csv(f"{data_dir}/{file_name}.csv", index_col=[0, 1])))
    data.append(
        set_budget_from_pop(pop=data[0], immunized_pop=data[1], active_cases=data[2], budget_pct=budget_pct)
    )
    return tuple(data)
