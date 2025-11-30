import os
from dotenv import load_dotenv
import uuid
from typing import Optional
from datetime import datetime, timezone
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents import LlmAgent,Agent, SequentialAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.google_llm import Gemini
from google.adk.tools import AgentTool
import json
import requests
from google.genai import types
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(
    filename="debug.log",
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

# Function
def search_item_walmart(product_name: str) -> dict:
    """
    Search for a product on Walmart and return the number of items, total pages, and formatted product details based on user input.
    Args:
        product_name (str): Name of the product to search.
    Returns:
        Dictionary with number_of_items, total_pages, and formatted products list, e.g., {'number_of_items': 224, 'total_pages': 10, 'products': [...]}.
        Error: {"error": "Failed to fetch data from Walmart"}
    """
    logger.info("Searching for '%s' on Walmart...", product_name)
    def product_offer(product_dict):
        for item in product_dict['specificationGroups'][:4]:
            if item['name'] == 'Exclusivo en línea':
                return item['specifications'][0]['name']
        return 'No hay oferta Exclusiva en línea'

    url = f"https://www.walmart.com.gt/{product_name}?_q={product_name}&map=ft&page=1&__pickRuntime=appsEtag%2Cblocks%2CblocksTree%2Ccomponents%2CcontentMap%2Cextensions%2Cmessages%2Cpage%2Cpages%2Cquery%2CqueryData%2Croute%2CruntimeMeta%2Csettings&__device=desktop"
    response = requests.get(url)
    if response.status_code != 200:
        return {"error": "Failed to fetch data from Walmart"}

    data_page = response.json()
    items_page = data_page['extensions']['store.search']['props']['context']['maxItemsPerPage']

    # Extract number of products and product data
    for item in data_page['queryData'][:1]:
        data_json_str = item["data"]
        parsed_data = json.loads(data_json_str)['productSearch']
        number_products = parsed_data['recordsFiltered']
        data_items = parsed_data['products']

    # Calculate total pages
    total_pages = int(number_products / items_page) if items_page > 0 else 0

    # Format products into JSON list
    products_list = []
    for product in (data_items):
        # Extract image url
        image_urls = [image['imageUrl'] for item in product.get('items', []) for image in item.get('images', [])]

        # Determine if there is an offer
        has_oferta = product['priceRange']['listPrice']['highPrice'] != product['priceRange']['sellingPrice']['lowPrice']
        has_exclusivo = product_offer(product) != 'No hay oferta Exclusiva en línea'

        # Choose price: lower if oferta or exclusivo, else higher
        if has_oferta or has_exclusivo:
            selected_price = product['priceRange']['sellingPrice']['lowPrice']
        else:
            selected_price = product['priceRange']['listPrice']['highPrice']

        product_json = {
            "productName": product['productName'],
            "imageUrl": image_urls[0] if image_urls else None,
            "brand": product['brand'],
            "selectedPrice": selected_price,
            "hasOferta": 'Oferta' if has_oferta else 'No hay oferta',
            "exclusivo": product_offer(product),
            "link": f"https://www.walmart.com.gt{product['link']}"
        }
        products_list.append(product_json)
    print(f"Done searching for '{product_name}'. Found {number_products} items across {total_pages} pages.") # Logging statement
    # Done searching the # number of items
    print(f" ✅Total items found: {items_page} of page 1 use for this DEMO.") # Logging statement
    return {
        "products": products_list
    }

def before_agent_callback(callback_context: CallbackContext) -> Optional[types.Content]:
    if "session_id" not in callback_context.state:
        callback_context.state["session_id"] = str(uuid.uuid4())

    callback_context.state["interaction_start_time"] = datetime.now(timezone.utc)
    request_num = callback_context.state.get("request_counter", 0) + 1
    callback_context.state["request_counter"] = request_num

    print(
        f"\n[BEFORE AGENT - SID: {callback_context.state['session_id']}] Interaction #{request_num} initiated."
    )
    print(f"Timestamp: {callback_context.state['interaction_start_time']}")
    print("\n\n")
    # Here you could also log incoming user_id if passed via context
    return None


def after_agent_callback(callback_context: CallbackContext) -> Optional[types.Content]:
    start_time = callback_context.state.get("interaction_start_time")
    duration_str = "N/A"
    if start_time:
        duration = datetime.now(timezone.utc) - start_time
        duration_str = f"{duration.total_seconds():.2f}s"

    print(
        f"\n[AFTER AGENT - SID: {callback_context.state['session_id']}] Interaction #{callback_context.state['request_counter']} completed."
    )
    print(f"Duration: {duration_str}")
    print("\n\n")
    # Potentially log final response or any errors encountered
    # callback_context.state can be used to persist metrics for the session
    return None

# Load environment variables
load_dotenv()
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"

# From openrouter, if needed
model = LiteLlm(
    model="openrouter/x-ai/grok-4.1-fast",
api_key= os.getenv("OPENAI_API_KEY"),
)

# Retry configuration
retry_config = types.HttpRetryOptions(
    attempts=3,  # Maximum retry attempts
    exp_base=7,  # Delay multiplier
    initial_delay=1,
    http_status_codes=[429, 500, 503, 504],  # Retry on these HTTP errors
)

# Define Agents
search_agent = Agent(
    name="shop_assistant",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""
   You are a smart shop assistant, your only job is to only the execute the `search_item_walmart()` tool with
   the item. Follow these steps:
   1. Use `search_item_walmart()` to search for the product on Walmart and
    retrieve the number of items. (The function return the following response
     while searching {Searching for 'Pan' on Walmart... Done searching for 'Pan'.
     Found 298 items across 14 pages. ✅Total items found: 21"})
    2. Dont provide any other information.
    3. If item not provide by the user, ask politely for the item to search.
    4. If the tool returns an error, inform the user politely.
    """,
    tools=[search_item_walmart],
    output_key="products_summary"
)

deal_comparison_agent = Agent(
    name='Deal_Comparison_Agent',
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""
    You are a deal comparison agent that will use the information from {{products_summary}} to answer the user's query
    by provide a clear summary of the top 5 products. Follow these steps:
    1. Analyze the list of products from {{products_summary}}.
    2. Compare prices and features of the products.
    3. Identify the best deals based on price and features.
    4. Summarize the findings, highlighting the best deals and their key features.
    """,
    output_key="final_summary"
)

sequential_agent = SequentialAgent(
    name="sequential_agent",
    sub_agents=[search_agent, deal_comparison_agent],
    description="Agents that searches for a product and compares prices to find the best deal."
)

root_agent = LlmAgent(
    name="root_agent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""
    You are the root agent that coordinates the shopping assistant process and guides the user through the steps.
    1. Greet the user and ask what product they would like to search for. 
    2. Finally, present the final summary obtained from the sequential_agent.
    """,
    tools = [
        AgentTool(sequential_agent)
    ],
    before_agent_callback=before_agent_callback,
    after_agent_callback=after_agent_callback,
)