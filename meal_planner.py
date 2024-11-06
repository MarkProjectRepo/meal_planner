import logging
from fasthtml.common import *
import httpx
import json
from logging.handlers import RotatingFileHandler
import csv
from datetime import datetime
import math
from config import *  # Import configuration values

# Set up console logging
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
console_handler.setFormatter(console_formatter)

# Set up file logging
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT)
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
file_handler.setFormatter(file_formatter)

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# Prevent logger from propagating messages to the root logger
logger.propagate = False
generated_meals = set()

app, rt = fast_app(pico=True)

async def generate_meal(ingredients, other_meals):
    logger.info(f"Generating meal with ingredients: {ingredients} and other meals: {other_meals}")
    system_message = "You are a helpful AI assistant that generates diverse meal suggestions in JSON format based on given ingredients and considering other meals for the week."
    
    example_outputs = [
        {
            "title": "Vegetarian Lentil Curry",
            "ingredients": "lentils\nonions\ngarlic\nginger\ntomatoes\ncoconut milk\ncurry powder\nrice"
        },
        {
            "title": "Grilled Salmon with Roasted Vegetables",
            "ingredients": "salmon fillet\nbell peppers\nzucchini\nred onion\nolive oil\nlemon\nrosemary\nsalt\npepper"
        }
    ]
    
    prompt = f"""
    System: {system_message}
    
    Human: Given these ingredients: {ingredients}, suggest a dinner meal. 
    Other meals planned for the week are: {other_meals}
    
    Be creative and diverse in your suggestions, but under no circumstances should you ignore the above suggested ingredients.
    The meal MUST expand on the Human provided ingredients.
    Maintain cultural consistency with the other meals unless there's a compelling reason for fusion.
    If given ambiguous ingredients, use your judgment to specify.
    
    Format your response as JSON with 'title' and 'ingredients' keys, where 'title' is the name of the meal.
    'ingredients' is a newline-separated list of the ingredients, do not add ANY OTHER FORMATTING or there will be suffering in the world, only a list of ingredients separated by the newline character.
    
    Example outputs (focus on the structure, not the specific ingredients):
    {json.dumps(example_outputs, indent=2)}
    
    Now, generate a meal suggestion based on these ingredients: {ingredients}
    
    Assistant: Here's a meal suggestion based on the given ingredients and considering the other meals:
    """
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                },
                timeout=OLLAMA_TIMEOUT
            )
        
        response.raise_for_status()
        
        result = response.json()
        generated_text = result['response']
        logger.info(f"Generated text: {generated_text}")
        
        # Try to extract JSON from the generated text
        json_start = generated_text.find('{')
        json_end = generated_text.rfind('}') + 1
        if json_start != -1 and json_end != -1:
            json_str = generated_text[json_start:json_end]
            parsed_result = json.loads(json_str)
        else:
            parsed_result = json.loads(generated_text)
        
        if isinstance(parsed_result, dict) and 'title' in parsed_result and 'ingredients' in parsed_result:
            return parsed_result
        else:
            logger.error(f"Invalid response format: {parsed_result}")
            return {"title": "Invalid response format", "ingredients": ingredients}
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        return {"title": "Error parsing response", "ingredients": ingredients}
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
        return {"title": f"HTTP error: {e.response.status_code}", "ingredients": ingredients}
    except httpx.RequestError as e:
        logger.error(f"Request error: {str(e)}")
        return {"title": "Error connecting to Ollama", "ingredients": ingredients}
    except Exception as e:
        logger.exception(f"Unexpected error in generate_meal: {str(e)}")
        return {"title": "Unexpected error", "ingredients": ingredients}

async def generate_ingredients():
    logger.info("Generating list of primary ingredients with focus on proteins")
    prompt = """
    Generate a list of 10 diverse primary ingredients suitable for various meals, with a focus on proteins and common ingredients.
    Each item should be a single ingredient, not a dish or recipe.
    Aim for a mix of:
    - 5-6 protein sources (meats, fish, legumes, etc.)
    - 2-3 vegetables
    - 1-2 grains or starches
    - 1 wild card ingredient (could be a fruit, herb, or unique item)
    
    Each ingredient MUST be unique.
    Format the response as a JSON array of strings with the key "ingredients" and NOTHING ELSE.
    Example: {"ingredients": ["Chicken breast", "Salmon", "Tofu", "Black beans", "Quinoa", "Broccoli", "Sweet potato", "Spinach", "Brown rice", "Mango"]}
    """
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                },
                timeout=OLLAMA_TIMEOUT
            )
        
        response.raise_for_status()
        result = response.json()
        generated_text = result['response']
        logger.info(f"Generated text: {generated_text}")

        # Try to parse the JSON response
        try:
            parsed_result = json.loads(generated_text)
            if isinstance(parsed_result, dict) and 'ingredients' in parsed_result:
                ingredients = parsed_result['ingredients']
            elif isinstance(parsed_result, list):
                ingredients = parsed_result
            else:
                raise ValueError("Unexpected JSON structure")
        except json.JSONDecodeError:
            # If JSON parsing fails, try to extract a list from the text
            import re
            ingredients = re.findall(r'"([^"]*)"', generated_text)
        
        # Ensure we have a list of strings
        ingredients = [str(item).strip() for item in ingredients if item]
        
        # Limit to 10 unique ingredients
        ingredients = list(dict.fromkeys(ingredients))[:10]
        
        if not ingredients:
            raise ValueError("No valid ingredients found")
        
        logger.info(f"Parsed ingredients: {ingredients}")
        return ingredients
    except Exception as e:
        logger.exception(f"Error generating ingredients: {str(e)}")
        return ["Chicken breast", "Salmon", "Ground beef", "Tofu", "Lentils", "Broccoli", "Sweet potato", "Quinoa", "Spinach", "Avocado"]

# Add this new function to generate the shopping list
async def generate_shopping_list(meals_and_ingredients):
    logger.info(f"Generating sorted shopping list with meals and ingredients: {meals_and_ingredients}")
    if not meals_and_ingredients.strip():
        logger.warning("No meals and ingredients provided for shopping list generation")
        return []

    system_message = "You are a helpful AI assistant that generates organized shopping lists based on meal ingredients for the week."
    
    example_output = {
        "shopping_list": [
            {"item": "Chicken breast", "meals": ["Monday: Grilled Chicken", "Thursday: Chicken Stir-Fry"]},
            {"item": "Broccoli", "meals": ["Monday: Grilled Chicken", "Wednesday: Vegetable Soup"]},
            {"item": "Carrots", "meals": ["Miscellaneous"]},
            {"item": "Olive oil", "meals": ["General ingredient"]},
            {"item": "Salt", "meals": ["General ingredient"]},
            {"item": "Black pepper", "meals": ["General ingredient"]},
        ]
    }
    
    prompt = f"""
    System: {system_message}
    
    Human: Create a sorted shopping list based on the following meals and ingredients for the week:
    {meals_and_ingredients}

    Please follow these guidelines:
    1. Combine similar ingredients across different meals.
    2. Sort the ingredients from most important to least important where importance is hierachical, Protein > Vegetable > Fruit > Grain  > Spices.
    3. Remove any duplicate items.
    4. If an ingredient is very specific, generalize it for the shopping list.
    5. For each item, list the meals it's used in.
    6. For common ingredients like salt, pepper, or oil, just list "General ingredient" for the meals.
    7. If an ingredient is associated with a day that has no meal title, list "Miscellaneous" for that meal.

    Format your response as JSON with a 'shopping_list' key containing an array of objects. Each object should have 'item' and 'meals' keys.
    
    Example output (focus on the structure):
    {json.dumps(example_output, indent=2)}
    
    Notice that even though Carrots are "Miscellaneous", it is still ranked higher than Olive oil and Salt as it is a feature ingredient.
    Now, generate a shopping list based on these meals and ingredients: {meals_and_ingredients}
    
    Assistant: Here's a sorted shopping list based on the given meals and ingredients:
    """
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                },
                timeout=OLLAMA_TIMEOUT
            )
        
        response.raise_for_status()
        result = response.json()
        generated_text = result['response']
        logger.info(f"Generated shopping list text: {generated_text}")
        
        parsed_result = json.loads(generated_text)
        
        if isinstance(parsed_result, dict) and 'shopping_list' in parsed_result:
            shopping_list = parsed_result['shopping_list']
        else:
            raise ValueError("Unexpected JSON structure")
        
        logger.info(f"Parsed shopping list: {shopping_list}")
        return shopping_list
    except Exception as e:
        logger.exception(f"Error generating shopping list: {str(e)}")
        return [{'item': "Error generating shopping list", 'meals': [str(e)]}]

def generate_wiggle_animation(duration=5000, max_rotation=200):
    frames = []
    for t in range(0, duration, 50):  # 50ms intervals
        progress = t / duration
        rotation = math.sin(t / 50) * (max_rotation - progress * max_rotation)
        frames.append(f"{t}ms {{ transform: rotate({rotation}deg); }}")
    
    return "\n".join(frames)

def wiggle_button(button_id):
    animation_name = f"wiggle_{button_id}"
    keyframes = generate_wiggle_animation()
    
    return [
        Style(f"""
            @keyframes {animation_name} {{
                {keyframes}
            }}
            #{button_id} {{
                animation: {animation_name} 2s ease-in-out;
            }}
        """),
        Script(f"""
            document.getElementById('{button_id}').addEventListener('animationend', function() {{
                this.style.animation = '';
            }});
        """)
    ]

@rt("/")
def get():
    global generated_meals
    generated_meals.clear()
    logger.info("Rendering initial page")
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    
    day_cards = [
        Div(
            H3(day, cls="day-title"),
            Div(
                Input(placeholder="Dinner", name=f"{day.lower()}_dinner", id=f"{day.lower()}_dinner", value=""),
                Textarea(placeholder="Ingredients", name=f"{day.lower()}_ingredients", id=f"{day.lower()}_ingredients", value=""),
                Div(
                    Button("Generate", 
                           hx_post=f"/generate/{day.lower()}", 
                           hx_target=f"#{day.lower()}_card",
                           hx_include=f"#{day.lower()}_dinner,#{day.lower()}_ingredients"),
                    Span(cls="loading-spinner"),
                    cls="button-container"
                ),
                cls="card-content"
            ),
            cls="day-card",
            id=f"{day.lower()}_card",
            ondragover="event.preventDefault();",
            ondrop=f"drop(event, '{day.lower()}')"
        ) for day in days
    ]
    
    ingredient_list = Div(
        H2("Primary Ingredients", cls="ingredient-title"),
        Ul(id="ingredient-list", cls="ingredient-list"),
        Div(
            Button("Generate Ingredients", 
                   hx_post="/generate_ingredients", 
                   hx_target="#ingredient-list",
                   cls="generate-ingredients-btn"),
            Span(cls="loading-spinner"),
            cls="button-container"
        ),
        cls="ingredient-section"
    )
    
    shopping_list_section = Div(
        H2("Shopping List", cls="shopping-list-title"),
        Div(
            Button("Generate Shopping List", 
                   hx_post="/generate_shopping_list", 
                   hx_target="#shopping-list",
                   hx_include=".meal-grid input, .meal-grid textarea",
                   cls="generate-shopping-list-btn"),
            Span(cls="loading-spinner"),
            cls="button-container"
        ),
        Ul(id="shopping-list", cls="shopping-list"),
        cls="shopping-list-section"
    )
    
    content = Div(
        H1("Weekly Dinner Planner", cls="main-title"),
        ingredient_list,
        Div(*day_cards, cls="meal-grid"),
        shopping_list_section,
        cls="container"
    )
    
    styles = Style("""
        @import url('https://fonts.googleapis.com/css2?family=VT323&display=swap');

        body {
            background: linear-gradient(45deg, #ff6ad5, #c774e8, #ad8cff, #8795e8, #94d0ff);
            background-size: 400% 400%;
            animation: gradient 15s ease infinite;
            color: #ecf0f1;
            font-family: 'VT323', monospace;
            margin: 0;
            padding: 0;
        }

        @keyframes gradient {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }

        .main-title {
            font-size: 4rem;
            text-align: center;
            color: #00ffff;
            text-shadow: 3px 3px #ff00ff;
            margin-bottom: 2rem;
        }

        .ingredient-section {
            background: rgba(0, 0, 0, 0.3);
            border-radius: 16px;
            padding: 1rem;
            margin-bottom: 2rem;
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
        }

        .ingredient-title {
            font-size: 2rem;
            color: #00ffff;
            margin-bottom: 1rem;
            text-shadow: 2px 2px #ff00ff;
        }

        .ingredient-list {
            display: flex;
            flex-wrap: wrap;
            gap: 0.75rem;
            list-style-type: none;
            padding: 0;
        }

        .ingredient-item {
            background: rgba(255, 255, 255, 0.2);
            padding: 0.5rem 1rem;
            border-radius: 20px;
            cursor: move;
            font-size: 1.2rem;
            color: #ffffff;
            text-shadow: 1px 1px #ff00ff;
            transition: all 0.3s ease;
        }

        .ingredient-item:hover {
            background: rgba(255, 255, 255, 0.3);
            transform: scale(1.05);
        }

        .generate-ingredients-btn {
            margin-top: 1rem;
        }

        .meal-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1.5rem;
        }

        .day-card {
            background: rgba(0, 0, 0, 0.3);
            border-radius: 16px;
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(5px);
            border: 1px solid rgba(255, 255, 255, 0.3);
            overflow: hidden;
            transition: transform 0.3s ease;
        }

        .day-card:hover {
            transform: translateY(-5px);
        }

        .day-title {
            font-size: 2rem;
            margin: 0;
            padding: 1rem;
            background: rgba(0, 255, 255, 0.3);
            color: #ffffff;
            text-align: center;
            text-shadow: 2px 2px #ff00ff;
        }

        .card-content {
            padding: 1rem;
        }

        input, textarea {
            width: 100%;
            padding: 0.5rem;
            margin-bottom: 0.5rem;
            border: none;
            border-radius: 4px;
            background-color: rgba(255, 255, 255, 0.2);
            color: #ffffff;
            font-family: 'VT323', monospace;
            font-size: 1rem;
        }

        textarea {
            height: 80px;
            resize: vertical;
        }

        button {
            width: 100%;
            padding: 0.5rem;
            background-color: #ff00ff;
            color: #ffffff;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-family: 'VT323', monospace;
            font-size: 1rem;
            transition: background-color 0.3s ease;
        }

        button:hover {
            background-color: #00ffff;
            color: #000000;
        }

        @media (max-width: 768px) {
            .meal-grid {
                grid-template-columns: 1fr;
            }
        }

        .shopping-list-section {
            background: rgba(0, 0, 0, 0.3);
            border-radius: 16px;
            padding: 1rem;
            margin-top: 2rem;
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
        }

        .shopping-list-title {
            font-size: 2rem;
            color: #00ffff;
            margin-bottom: 1rem;
            text-shadow: 2px 2px #ff00ff;
        }

        .shopping-list {
            list-style-type: none;
            padding: 0;
            max-width: 600px;
            margin: 0 auto;
        }

        .shopping-list-item {
            background: rgba(255, 255, 255, 0.2);
            padding: 0.75rem 1rem;
            margin-bottom: 0.5rem;
            border-radius: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 1.1rem;
        }

        .shopping-list-item span {
            flex-grow: 1;
            margin-right: 1rem;
            word-break: break-word;
        }

        .remove-item-btn {
            background: none;
            border: none;
            color: #ff00ff;
            cursor: pointer;
            font-size: 1.2rem;
            padding: 0;
            width: 24px;
            height: 24px;
            line-height: 24px;
            text-align: center;
            flex-shrink: 0;
        }

        .remove-item-btn:hover {
            color: #00ffff;
        }

        .generate-shopping-list-btn {
            background-color: #ff00ff;
            color: #ffffff;
            border: none;
            border-radius: 8px;
            padding: 0.75rem 1.5rem;
            font-size: 1.1rem;
            cursor: pointer;
            transition: background-color 0.3s ease;
            margin-bottom: 1rem;
        }

        .generate-shopping-list-btn:hover {
            background-color: #00ffff;
            color: #000000;
        }

        .save-message {
            margin-top: 1rem;
            font-style: italic;
            color: #00ffff;
        }

        .htmx-indicator {
            display: none;
        }
        .htmx-request .htmx-indicator {
            display: inline-block;
        }
        .loading-spinner {
            display: none;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(255,255,255,.3);
            border-radius: 50%;
            border-top-color: #fff;
            animation: spin 1s ease-in-out infinite;
            margin-left: 10px;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .button-container {
            display: flex;
            align-items: center;
        }

        button {
            transition: transform 0.3s ease;
        }

        .wiggle {
            animation: none;
            transition: transform 0.1s ease-in-out;
        }

        @keyframes wiggle {
            0%, 100% { transform: rotate(0deg); }
            25% { transform: rotate(-3deg); }
            75% { transform: rotate(3deg); }
        }

        .export-btn {
            background-color: #4CAF50;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
            margin-top: 10px;
        }

        .export-btn:hover {
            background-color: #45a049;
        }
    """)
    
    scripts = Script("""
        function drag(event) {
            event.dataTransfer.setData("text", event.target.innerText);
        }

        function drop(event, day) {
            event.preventDefault();
            var ingredient = event.dataTransfer.getData("text");
            var textarea = document.getElementById(day + '_ingredients');
            textarea.value += (textarea.value ? '\\n' : '') + ingredient;
            
            // Trigger meal generation
            var generateBtn = event.target.closest('.day-card').querySelector('button');
            generateBtn.click();
        }

        function removeShoppingItem(event) {
            event.preventDefault();
            event.target.closest('li').remove();
        }

        function wiggleButton(button) {
            let start = null;
            const duration = 10000;  // 10 seconds
            const animateWiggle = (timestamp) => {
                if (!start) start = timestamp;
                const progress = timestamp - start;
                const rotation = Math.sin(progress / 100) * (3 - progress / duration * 3);
                button.style.transform = `rotate(${rotation}deg)`;
                if (progress < duration) {
                    requestAnimationFrame(animateWiggle);
                } else {
                    button.style.transform = '';
                }
            };
            requestAnimationFrame(animateWiggle);
        }

        document.body.addEventListener('htmx:beforeRequest', function(event) {
            var button = event.target.closest('button');
            if (button) {
                wiggleButton(button);
            }
        });

        document.body.addEventListener('htmx:afterRequest', function(event) {
            var button = event.target.closest('button');
            if (button) {
                button.style.transform = '';
            }
        });
    """)
    
    return Titled("Weekly Dinner Planner", content, styles, scripts)

@rt("/generate_ingredients")
async def post():
    ingredients = await generate_ingredients()
    return Ul(*[Li(ingredient, cls="ingredient-item", draggable="true", ondragstart="drag(event)") for ingredient in ingredients], cls="ingredient-list")

@rt("/generate/{day}")
async def post(day: str, request):
    global generated_meals
    logger.debug(f"POST request received for /generate/{day}")
    form = await request.form()
    logger.debug(f"Raw form data: {dict(form)}")

    ingredients = form.get(f"{day}_ingredients", "").strip()
    logger.debug(f"Extracted ingredients for {day}: {ingredients}")
    
    # Gather other meals from the global set
    other_meals = [meal for meal in generated_meals if not meal.startswith(f"{day.capitalize()}:")]
    other_meals_str = ", ".join(other_meals)
    logger.debug(f"Other meals: {other_meals_str}")
    
    logger.info(f"Generating meal for {day} with ingredients: {ingredients}")
    
    try:
        meal = await generate_meal(ingredients, other_meals_str)
        logger.debug(f"Generated meal: {meal}")
        # Add the generated meal to the global set
        generated_meals.add(f"{day.capitalize()}: {meal['title']}")
    except Exception as e:
        logger.exception(f"Error in post function: {str(e)}")
        meal = {"title": "Error generating meal", "ingredients": ingredients}
    
    button_id = f"generate_button_{day}"
    return Div(
        H3(day.capitalize(), cls="day-title"),
        Div(
            Input(value=meal['title'], name=f"{day}_dinner", id=f"{day}_dinner"),
            Textarea(meal['ingredients'], name=f"{day}_ingredients", id=f"{day}_ingredients"),
            Button("Generate Meal", 
                   id=button_id,
                   hx_post=f"/generate/{day}", 
                   hx_target=f"#{day}_card", 
                   hx_include=f"#{day}_dinner,#{day}_ingredients,.meal-grid input, .meal-grid textarea"),
            *wiggle_button(button_id),
            cls="card-content"
        ),
        cls="day-card",
        id=f"{day}_card"
    )

# Add a new route to handle shopping list generation
@rt("/generate_shopping_list")
async def post(request):
    global generated_meals
    form = await request.form()
    logger.debug(f"Raw form data for shopping list: {dict(form)}")

    meals_and_ingredients = []
    for day in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]:
        ingredients = form.get(f"{day}_ingredients", "").strip()
        logger.debug(f"{day.capitalize()} - Ingredients: {ingredients}")
        if ingredients:
            meal_title = next((meal for meal in generated_meals if meal.startswith(f"{day.capitalize()}:")), f"{day.capitalize()}: Miscellaneous")
            meals_and_ingredients.append(f"{meal_title}\nIngredients: {ingredients}")

    all_data_str = "\n\n".join(meals_and_ingredients)
    logger.info(f"Collected meals and ingredients for shopping list:\n{all_data_str}")

    if not all_data_str:
        logger.warning("No meals and ingredients collected for shopping list")
        return Ul(Li("No meals and ingredients provided. Please add meals and ingredients for the week.", cls="shopping-list-item"), id="shopping-list", cls="shopping-list")

    try:
        shopping_list = await generate_shopping_list(all_data_str)

        if not shopping_list:
            logger.warning("Empty shopping list generated")
            return Ul(Li("No items in shopping list", cls="shopping-list-item"), id="shopping-list", cls="shopping-list")

        # Save to CSV
        timestamp = datetime.now().strftime(EXPORT_DATE_FORMAT)
        filename = f"{EXPORT_FILENAME_PREFIX}_{timestamp}.csv"
        with open(filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Item', 'Meals'])
            for item in shopping_list:
                writer.writerow([item['item'], ', '.join(item['meals'])])

        logger.info(f"Shopping list saved to {filename}")

        return Div(
            Ul(*[
                Li(
                    Span(f"{item['item']} - {', '.join(item['meals'])}"),
                    Button("×", cls="remove-item-btn", onclick="removeShoppingItem(event)"),
                    cls="shopping-list-item"
                ) for item in shopping_list
            ], id="shopping-list", cls="shopping-list"),
            P(f"Shopping list saved to {filename}", cls="save-message"),
            Button("Regenerate Shopping List",
                   id="regenerate_button",
                   hx_post="/generate_shopping_list",
                   hx_target="#shopping-list",
                   hx_include=".meal-grid input, .meal-grid textarea"),
            Button("Export Shopping List",
                   id="export_button",
                   hx_post="/export_shopping_list",
                   hx_include=".shopping-list-text",  # Update to target the span elements
                   hx_target="#export-result"),
            Div(id="export-result")
        )
    except Exception as e:
        logger.exception(f"Error in shopping list generation route: {str(e)}")
        return Ul(Li(f"Error: {str(e)}", cls="shopping-list-item"), id="shopping-list", cls="shopping-list")

@rt("/export_shopping_list")
async def post(request):
    form = await request.form()
    logger.debug(f"Raw form data for export: {dict(form)}")
    
    # Get all the shopping list items from the form
    shopping_list_items = form.getlist("shopping-list-item")

    logger.debug(f"Shopping list items: {shopping_list_items}")

    processed_list = {}
    for item in shopping_list_items:
        if " - " in item:
            item_name, meals = item.split(" - ", 1)
        else:
            item_name, meals = item, "Unspecified"
        
        if item_name in processed_list:
            processed_list[item_name]['count'] += 1
            processed_list[item_name]['meals'] = f"{processed_list[item_name]['meals']}, {meals}"
        else:
            processed_list[item_name] = {'count': 1, 'meals': meals}

    # Generate CSV content
    csv_content = "Item,Quantity,Meals\n"
    for item, details in processed_list.items():
        csv_content += f"{item},{details['count']},{details['meals']}\n"

    # Generate a new filename with timestamp
    timestamp = datetime.now().strftime(EXPORT_DATE_FORMAT)
    filename = f"{EXPORT_FILENAME_PREFIX}_{timestamp}.csv"

    headers = {
        "Content-Disposition": f"attachment; filename={filename}",
        "Content-Type": "text/csv"
    }
    return Response(content=csv_content, headers=headers)

serve()
