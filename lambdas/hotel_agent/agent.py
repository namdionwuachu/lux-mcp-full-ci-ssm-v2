"""Hotel agent: fetch candidates via provider, then 4★+gym filter + pool bonus."""
from typing import Dict, Any
from shared.models import Stay
from lambdas.orchestrator.tools.web_search import search_hotels_marais_with_gym_and_pool
from lambdas.orchestrator.tools.hotels_filter import filter_four_star_with_gym
def run(task: Dict[str, Any]) -> Dict[str, Any]:
    stay = Stay(**task["stay"]); c = search_hotels_marais_with_gym_and_pool(stay); hotels = filter_four_star_with_gym(c); return {"status":"ok","hotels":hotels}
