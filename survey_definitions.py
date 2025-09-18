# Hardcoded Logistics Operations Health Assessment Framework
# Levels: Zone, Region, City, Branch
# For each level we define categories (name, weight) and 50 questions with: text, weight, formula (RAW_PERCENT|HIB|LIB) and target

from typing import Dict, List, TypedDict, Optional


class QuestionDef(TypedDict):
	text: str
	weight: float
	formula: str  # RAW_PERCENT|HIB|LIB
	target: float


class CategoryDef(TypedDict):
	name: str
	weight: float
	questions: List[QuestionDef]


Framework = Dict[str, List[CategoryDef]]


def infer_default_target(text: str, formula: str) -> float:
	low = text.lower()
	if formula == "RAW_PERCENT":
		return 100.0
	# Lower-is-better common targets
	if formula == "LIB":
		if "min" in low:
			return 30.0
		if "hrs" in low or "hour" in low:
			return 24.0
		if "days" in low or "day" in low:
			return 7.0
		if "count" in low:
			return 5.0
		return 1.0
	# Higher-is-better numeric targets
	if "turnover" in low:
		return 10.0
	if "throughput" in low:
		return 100.0
	if "efficiency" in low or "utilization" in low:
		return 100.0
	return 100.0


def _q(text: str, weight: float = 10.0, formula: str = "HIB", target: Optional[float] = None) -> QuestionDef:
	tgt = target if target is not None else infer_default_target(text, formula)
	return {"text": text, "weight": weight, "formula": formula, "target": float(tgt)}


FRAMEWORK: Framework = {
	"Zone": [
		{"name": "Operational Efficiency", "weight": 20.0, "questions": [
			_q("On-time delivery rate (%) across the zone this month", formula="RAW_PERCENT"),
			_q("Perfect order rate (%) – deliveries complete and undamaged", formula="RAW_PERCENT"),
			_q("Avg order lead time (hrs; lower is better)", formula="LIB"),
			_q("Fleet utilization rate (%) (vehicles used vs available)", formula="RAW_PERCENT"),
			_q("Trailer utilization rate (%) (volume loaded vs capacity)", formula="RAW_PERCENT"),
			_q("Order accuracy rate (%) (orders with correct items)", formula="RAW_PERCENT"),
			_q("Damage-free shipment rate (%) (no cargo damage)", formula="RAW_PERCENT"),
			_q("Avg handling time per order (hrs; lower is better)", formula="LIB"),
			_q("Inventory turnover rate (times per month)"),
			_q("Facility uptime (%) (percent of time operational)", formula="RAW_PERCENT"),
		]},
		{"name": "Compliance & Safety", "weight": 20.0, "questions": [
			_q("Regulatory audit pass rate (%)", formula="RAW_PERCENT"),
			_q("Safety certification compliance rate (%)", formula="RAW_PERCENT"),
			_q("Safety training completion rate (%) this month", formula="RAW_PERCENT"),
			_q("Scheduled maintenance completion rate (%)"),
			_q("Vehicle inspection compliance (%)"),
			_q("Product quality compliance rate (%) (within specs)", formula="RAW_PERCENT"),
			_q("Workplace accident rate (per 1000 employees; lower is better)", formula="LIB"),
			_q("OSHA incident rate (per 100 employees; lower is better)", formula="LIB"),
			_q("Branches with zero compliance violations (%)", formula="RAW_PERCENT"),
			_q("Audit findings closure rate (%) (finding resolved on time)"),
		]},
		{"name": "Strategic Initiatives", "weight": 20.0, "questions": [
			_q("Strategic project completion rate (%) (on schedule)", formula="RAW_PERCENT"),
			_q("Forecast accuracy (%) (vs annual plan)", formula="RAW_PERCENT"),
			_q("Strategic budget adherence rate (%)", formula="RAW_PERCENT"),
			_q("Avg time to implement new service (days; lower is better)", formula="LIB"),
			_q("System uptime (%) (corporate systems)", formula="RAW_PERCENT"),
			_q("Employee turnover rate (%) (lower is better)", formula="LIB"),
			_q("Annual network capacity growth (%) (target vs actual)"),
			_q("New route launch rate (%) (vs plan)"),
			_q("IT project completion rate (%) (planned vs done)"),
			_q("ROI on strategic initiatives (%) (achieved vs planned)"),
		]},
		{"name": "Customer Service", "weight": 20.0, "questions": [
			_q("Customer satisfaction score (%) (survey)", formula="RAW_PERCENT"),
			_q("Customer on-time delivery rate (%)", formula="RAW_PERCENT"),
			_q("Order fill rate (%) (orders delivered in full)", formula="RAW_PERCENT"),
			_q("Avg complaint resolution time (days; lower is better)", formula="LIB"),
			_q("Annual customer retention rate (%)", formula="RAW_PERCENT"),
			_q("Invoice processing accuracy (%)", formula="RAW_PERCENT"),
			_q("SLA compliance rate (%) (contracts met)", formula="RAW_PERCENT"),
			_q("Avg inquiry response time (hrs; lower is better)", formula="LIB"),
			_q("Customer complaint rate (%) (lower is better)", formula="LIB"),
			_q("Net Promoter Score (%)", formula="RAW_PERCENT"),
		]},
		{"name": "Financial Performance", "weight": 20.0, "questions": [
			_q("Avg cost per order (USD; lower is better)", formula="LIB"),
			_q("Transportation cost (% of revenue; lower is better)", formula="LIB"),
			_q("Inventory carrying cost (% of value; lower is better)", formula="LIB"),
			_q("Budget variance (%) (under/over budget; lower is better)", formula="LIB"),
			_q("Profit margin (%)"),
			_q("Return on assets (%)"),
			_q("Fuel efficiency (miles/gallon)"),
			_q("Accounts receivable turnover"),
			_q("Working capital turnover"),
			_q("Overhead cost per branch (USD; lower is better)", formula="LIB"),
		]},
	],
	"Region": [
		{"name": "Transportation", "weight": 20.0, "questions": [
			_q("On-time shipment rate (%) for regional deliveries", formula="RAW_PERCENT"),
			_q("Average transit time (hours; lower is better)", formula="LIB"),
			_q("Truck turnaround rate (min at facility; lower is better)", formula="LIB"),
			_q("Fleet utilization (%) (regional vehicle usage)", formula="RAW_PERCENT"),
			_q("Freight cost per shipment (USD; lower is better)", formula="LIB"),
			_q("Transportation cost (% of regional revenue; lower is better)", formula="LIB"),
			_q("Percentage of regional shipments with accurate billing", formula="RAW_PERCENT"),
			_q("Average dwell time at regional hub (hrs; lower is better)", formula="LIB"),
			_q("Trailer load fill rate (%)", formula="RAW_PERCENT"),
			_q("Fuel cost per mile (USD; lower is better)", formula="LIB"),
		]},
		{"name": "Warehouse", "weight": 20.0, "questions": [
			_q("Inventory accuracy (%) at regional DCs", formula="RAW_PERCENT"),
			_q("Order picking accuracy (%)", formula="RAW_PERCENT"),
			_q("Average warehouse order cycle time (hrs; lower is better)", formula="LIB"),
			_q("On-time warehouse dispatch rate (%)", formula="RAW_PERCENT"),
			_q("Dock-to-stock cycle time (hrs; lower is better)", formula="LIB"),
			_q("Warehouse cost per unit (USD; lower is better)", formula="LIB"),
			_q("Warehouse space utilization (%)", formula="RAW_PERCENT"),
			_q("Shrinkage rate (%) (inventory loss; lower is better)", formula="LIB"),
			_q("Number of backorders per month (lower is better)", formula="LIB"),
			_q("Pallet movement per labor-hour (higher is better)"),
		]},
		{"name": "Process", "weight": 20.0, "questions": [
			_q("Shipments per employee (monthly)"),
			_q("Processing cost per shipment (USD; lower is better)", formula="LIB"),
			_q("Percentage of standard operating procedures followed", formula="RAW_PERCENT"),
			_q("Automation rate of manual processes (%)", formula="RAW_PERCENT"),
			_q("Regional process cycle time (total order to delivery, hrs; lower is better)", formula="LIB"),
			_q("Supply chain efficiency index (composite, higher is better)"),
			_q("Percentage of on-time project milestones", formula="RAW_PERCENT"),
			_q("IT systems uptime (%) (regional systems)", formula="RAW_PERCENT"),
			_q("Data accuracy rate (%) in key systems", formula="RAW_PERCENT"),
			_q("Percentage of operations supported by real-time tracking", formula="RAW_PERCENT"),
		]},
		{"name": "Safety", "weight": 20.0, "questions": [
			_q("Regional OSHA recordable incident rate (per 100 employees; lower is better)", formula="LIB"),
			_q("Safety training hours per employee (vs target)", formula="HIB"),
			_q("Number of safety audits completed on schedule (%)", formula="RAW_PERCENT"),
			_q("Incident response time (mins; lower is better)", formula="LIB"),
			_q("Work-related injury frequency (incidents per million hours; lower is better)", formula="LIB"),
			_q("Percentage of sites passing safety audit without findings", formula="RAW_PERCENT"),
			_q("Environmental compliance rate (%)", formula="RAW_PERCENT"),
			_q("Corrective actions closure rate (%) (on time)", formula="RAW_PERCENT"),
			_q("Lost-time incident rate (per 100 employees; lower is better)", formula="LIB"),
			_q("Percentage of safety equipment checks completed", formula="RAW_PERCENT"),
		]},
		{"name": "Customer", "weight": 20.0, "questions": [
			_q("Regional customer satisfaction score (%)", formula="RAW_PERCENT"),
			_q("Regional on-time response to customer inquiries (%)", formula="RAW_PERCENT"),
			_q("Percentage of repeat orders processed error-free", formula="RAW_PERCENT"),
			_q("Region-level perfect order rate (%) (no issues per order)", formula="RAW_PERCENT"),
			_q("Average lead time for regional orders (days; lower is better)", formula="LIB"),
			_q("Percentage of customer SLAs met", formula="RAW_PERCENT"),
			_q("On-time invoice generation (%)", formula="RAW_PERCENT"),
			_q("Average payment collection time (days; lower is better)", formula="LIB"),
			_q("Monthly customer complaint rate (%) (lower is better)", formula="LIB"),
			_q("Percentage of customer queries resolved within 24h", formula="RAW_PERCENT"),
		]},
	],
	"City": [
		{"name": "Delivery Efficiency", "weight": 20.0, "questions": [
			_q("City delivery on-time rate (%)", formula="RAW_PERCENT"),
			_q("Avg last-mile delivery time (min; lower is better)", formula="LIB"),
			_q("Delivery density (deliveries per route)"),
			_q("Vehicle loading rate (%) (used capacity vs total)", formula="RAW_PERCENT"),
			_q("Percentage of deliveries with digital proof-of-delivery", formula="RAW_PERCENT"),
			_q("Fuel efficiency for city fleet (km/liter)"),
			_q("Turnaround time for city hub reloading (min; lower is better)", formula="LIB"),
			_q("Backhaul utilization rate (%)", formula="RAW_PERCENT"),
			_q("On-time pickup rate (%)", formula="RAW_PERCENT"),
			_q("City-level shipment per driver per day"),
		]},
		{"name": "Inventory", "weight": 20.0, "questions": [
			_q("Branch inventory accuracy (%)", formula="RAW_PERCENT"),
			_q("Stockout rate (%) (lower is better)", formula="LIB"),
			_q("Cycle count completion rate (%)", formula="RAW_PERCENT"),
			_q("Days of inventory on hand (lower is better)", formula="LIB"),
			_q("Space utilization (%)", formula="RAW_PERCENT"),
			_q("Shrinkage (%) (lower is better)", formula="LIB"),
			_q("Expired or obsolete stock (%) (lower is better)", formula="LIB"),
			_q("Order fill time (hours; lower is better)", formula="LIB"),
			_q("Fill rate to customers (%)", formula="RAW_PERCENT"),
			_q("Inventory turnover (times/year)"),
		]},
		{"name": "Process", "weight": 20.0, "questions": [
			_q("Percentage of processes automated", formula="RAW_PERCENT"),
			_q("Staff training compliance (%) (completed required training)", formula="RAW_PERCENT"),
			_q("Adherence to standard pickup/check-in procedures (%)", formula="RAW_PERCENT"),
			_q("Order processing accuracy (%)", formula="RAW_PERCENT"),
			_q("Avg daily throughput (packages handled per day)"),
			_q("Call center response rate (%)", formula="RAW_PERCENT"),
			_q("Reports submitted on time (%)", formula="RAW_PERCENT"),
			_q("Percentage of branches meeting audit schedules", formula="RAW_PERCENT"),
			_q("Internal inventory audit pass rate (%)", formula="RAW_PERCENT"),
			_q("Percentage of escalations resolved within SLA (%)", formula="RAW_PERCENT"),
		]},
		{"name": "Safety & Compliance", "weight": 20.0, "questions": [
			_q("City-level incident rate (accidents per 100 employees; lower is better)", formula="LIB"),
			_q("PPE compliance (%) (personnel wearing required equipment)", formula="RAW_PERCENT"),
			_q("Number of safety audits passed (%)", formula="RAW_PERCENT"),
			_q("Compliance with local regulations (%)", formula="RAW_PERCENT"),
			_q("Environmental safety incidents (count; lower is better)", formula="LIB"),
			_q("Fire drill completion rate (%)", formula="RAW_PERCENT"),
			_q("Equipment inspection rate (%)", formula="RAW_PERCENT"),
			_q("Ergonomic training completion (%)", formula="RAW_PERCENT"),
			_q("Lost-time injury frequency (per 100 employees; lower is better)", formula="LIB"),
			_q("Compliance with waste disposal regulations (%)", formula="RAW_PERCENT"),
		]},
		{"name": "Customer", "weight": 20.0, "questions": [
			_q("In-city customer satisfaction (%)", formula="RAW_PERCENT"),
			_q("Percentage of orders delivered in full", formula="RAW_PERCENT"),
			_q("City-level complaint resolution rate (%)", formula="RAW_PERCENT"),
			_q("Average follow-up response time (hrs; lower is better)", formula="LIB"),
			_q("Customer repeat order rate (%)", formula="RAW_PERCENT"),
			_q("Local net promoter score (%)", formula="RAW_PERCENT"),
			_q("Timeliness of emergency orders (%)", formula="RAW_PERCENT"),
			_q("Percentage of customers enrolled in loyalty programs", formula="RAW_PERCENT"),
			_q("Feedback survey completion rate (%)", formula="RAW_PERCENT"),
			_q("Cancellation rate (%) (lower is better)", formula="LIB"),
		]},
	],
	"Branch": [
		{"name": "Daily Ops", "weight": 20.0, "questions": [
			_q("Shipments processed per day"),
			_q("On-time delivery rate (%) at branch", formula="RAW_PERCENT"),
			_q("Order picking accuracy (%)", formula="RAW_PERCENT"),
			_q("Shipments per labor-hour"),
			_q("Branch throughput vs plan (%)"),
			_q("Queue time at branch (mins; lower is better)", formula="LIB"),
			_q("Local customer complaints (%) (lower is better)", formula="LIB"),
			_q("Price quote accuracy (%)", formula="RAW_PERCENT"),
			_q("Order cycle time (hours from order to dispatch; lower is better)", formula="LIB"),
			_q("Stockout incidents per month (lower is better)", formula="LIB"),
		]},
		{"name": "Inventory", "weight": 20.0, "questions": [
			_q("Inventory count accuracy (%)", formula="RAW_PERCENT"),
			_q("Cycle count completion (%)", formula="RAW_PERCENT"),
			_q("Order fill rate (%)", formula="RAW_PERCENT"),
			_q("Inventory replenishment lead time (days; lower is better)", formula="LIB"),
			_q("Number of inventory adjustments (count; lower is better)", formula="LIB"),
			_q("Stock accuracy (negative adjustments) (%) (lower is better)", formula="LIB"),
			_q("Return rate (%) (customer returns; lower is better)", formula="LIB"),
			_q("Wastage/spoilage rate (%) (lower is better)", formula="LIB"),
			_q("Stock rotation index (times per month)"),
			_q("Inventory to sales ratio (target vs actual)"),
		]},
		{"name": "Safety & Compliance", "weight": 20.0, "questions": [
			_q("Branch OSHA incident rate (per 100 employees; lower is better)", formula="LIB"),
			_q("Safety checklist completion rate (%)", formula="RAW_PERCENT"),
			_q("Emergency drill completion (%)", formula="RAW_PERCENT"),
			_q("Personal protective equipment compliance (%)", formula="RAW_PERCENT"),
			_q("Number of safety violations this month (lower is better)", formula="LIB"),
			_q("Chemical handling compliance (%)", formula="RAW_PERCENT"),
			_q("Vehicle inspection rate (%)", formula="RAW_PERCENT"),
			_q("Safety incident response time (mins; lower is better)", formula="LIB"),
			_q("Percentage of equipment maintenance on schedule", formula="RAW_PERCENT"),
			_q("Compliance training rate (%)", formula="RAW_PERCENT"),
		]},
		{"name": "Process", "weight": 20.0, "questions": [
			_q("Standard operating procedure compliance (%)", formula="RAW_PERCENT"),
			_q("Number of non-conformance incidents (lower is better)", formula="LIB"),
			_q("Time to resolve customer issues (hrs; lower is better)", formula="LIB"),
			_q("Percentage of daily targets met", formula="RAW_PERCENT"),
			_q("Cross-docking rate (%)", formula="RAW_PERCENT"),
			_q("Order cycle time for priority orders (hrs; lower is better)", formula="LIB"),
			_q("Daily report submission on time (%)", formula="RAW_PERCENT"),
			_q("Percentage of courier pickups met", formula="RAW_PERCENT"),
			_q("Compliance with digital record-keeping (yes=100, no=0)", formula="HIB", target=100.0),
			_q("Parking space utilization (%)", formula="RAW_PERCENT"),
		]},
		{"name": "Equipment", "weight": 20.0, "questions": [
			_q("Equipment uptime (%)", formula="RAW_PERCENT"),
			_q("Preventive maintenance completion (%)", formula="RAW_PERCENT"),
			_q("Mean time to repair (hrs; lower is better)", formula="LIB"),
			_q("Number of equipment failures per month (lower is better)", formula="LIB"),
			_q("Percentage of safety checks done on equipment", formula="RAW_PERCENT"),
			_q("Inventory of spare parts accuracy (%)", formula="RAW_PERCENT"),
			_q("Calibration compliance (%)", formula="RAW_PERCENT"),
			_q("Avg downtime of critical machines (hrs; lower is better)", formula="LIB"),
			_q("Maintenance cost per unit ($; lower is better)", formula="LIB"),
			_q("Backlog of preventive tasks (count; lower is better)", formula="LIB"),
		]},
	],
}
