from typing import Dict, List, Tuple


def compute_question_score(actual: float, target: float, lower_is_better: bool = False) -> float:
	if target is None or target == 0:
		return 0.0
	score = (target / actual * 100.0) if lower_is_better else (actual / target * 100.0)
	if score < 0:
		score = 0.0
	if score > 100:
		score = 100.0
	return float(score)


def compute_survey_scores(cat_id_to_scores: Dict[int, List[Tuple[float, float]]]) -> Tuple[float, Dict[int, float]]:
	per_category_scores: Dict[int, float] = {}
	overall_weighted_sum = 0.0
	total_weight = 0.0
	for cid, score_items in cat_id_to_scores.items():
		cat_weighted_sum = 0.0
		cat_total_weight = 0.0
		for score, weight in score_items:
			w = weight / 100.0
			cat_weighted_sum += score * w
			cat_total_weight += w
			overall_weighted_sum += score * w
			total_weight += w
		cat_score = (cat_weighted_sum / cat_total_weight) if cat_total_weight > 0 else 0.0
		per_category_scores[cid] = cat_score
	overall = (overall_weighted_sum / total_weight) if total_weight > 0 else 0.0
	return overall, per_category_scores
