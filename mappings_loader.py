import json
import os
from typing import Dict, List


def load_mappings(path: str = "mappings.json") -> Dict:
	with open(path, "r") as f:
		return json.load(f)


def get_zones(m: Dict) -> List[str]:
	return sorted(list(m.keys()))


def get_regions(m: Dict, zone: str) -> List[str]:
	return sorted(list(m.get(zone, {}).keys()))


def get_cities(m: Dict, zone: str, region: str) -> List[str]:
	return sorted(list(m.get(zone, {}).get(region, {}).keys()))


def get_branches(m: Dict, zone: str, region: str, city: str) -> List[str]:
	return sorted(list(m.get(zone, {}).get(region, {}).get(city, {}).keys()))
