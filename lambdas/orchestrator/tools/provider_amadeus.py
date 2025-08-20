# provider_amadeus.py - Complete replacement
import json
import logging
from amadeus import Client, ResponseError
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Keep your existing global amadeus client initialization
amadeus = Client(
    client_id='YOUR_AMADEUS_API_KEY',
    client_secret='YOUR_AMADEUS_API_SECRET'
)

def search_hotels(stay_details: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Fixed hotel search - addresses the 400 error
    """
    # Add this debug line at the very beginning
    logger.info(f"🔧 FIXED VERSION RUNNING - Debug timestamp: {datetime.now()}")
    try:
        # Extract parameters
        city_code = stay_details.get('cityCode', 'PAR')
        adults = str(stay_details.get('adults', 2))
        check_in = stay_details.get('checkInDate', '2025-12-26')
        check_out = stay_details.get('checkOutDate', '2026-01-03')
        currency = stay_details.get('currency', 'GBP')
        rooms = str(stay_details.get('roomQuantity', 1))
        
        logger.info(f"Searching hotels in {city_code} for {adults} adults")
        
        # STEP 1: Get hotel IDs for the city first
        hotels_in_city = amadeus.reference_data.locations.hotels.by_city.get(
            cityCode=city_code
        )
        
        if not hotels_in_city.data:
            logger.warning(f"No hotels found in city {city_code}")
            return []
        
        # STEP 2: Extract hotel IDs (limit for performance)
        hotel_ids = [hotel.get('hotelId') for hotel in hotels_in_city.data[:20]]
        logger.info(f"Found {len(hotel_ids)} hotels in {city_code}")
        
        # STEP 3: Search for offers using hotel IDs
        offers_response = amadeus.shopping.hotel_offers_search.get(
            hotelIds=hotel_ids,  # Fixed: use hotel IDs, not city code
            adults=adults,
            checkInDate=check_in,
            checkOutDate=check_out,
            currency=currency,
            roomQuantity=rooms,
            bestRateOnly=True
        )
        
        logger.info(f"Found {len(offers_response.data)} hotel offers")
        return offers_response.data
        
    except ResponseError as error:
        logger.error(f"Amadeus API Error: {error}")
        return []  # Don't crash, return empty list
        
    except Exception as error:
        logger.error(f"Unexpected error in hotel search: {error}")
        return []

def _amadeus_search(search_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Wrapper function that your existing code calls
    """
    return search_hotels(search_data)

# Add any other functions your existing code uses
def get_hotel_ratings(hotel_id: str) -> Dict:
    """Get hotel sentiment/ratings"""
    try:
        response = amadeus.e_reputation.hotel_sentiments.get(hotelIds=hotel_id)
        return response.data
    except ResponseError as error:
        logger.error(f"Failed to get ratings for {hotel_id}: {error}")
        return {}

def search_activities(latitude: float, longitude: float) -> Dict:
    """Search activities by location"""
    try:
        response = amadeus.shopping.activities.get(
            latitude=latitude,
            longitude=longitude
        )
        return response.data
    except ResponseError as error:
        logger.error(f"Failed to search activities: {error}")
        return [] 
