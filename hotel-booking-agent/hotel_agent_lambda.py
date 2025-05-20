import boto3
import json
import os
import uuid
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key, Attr
from decimal import Decimal

# Initialize DynamoDB resources
dynamodb_resource = boto3.resource('dynamodb')
hotels_table = os.getenv('hotels_table', 'hotel-agent-348d2ff0-hotels')
hotels_pk = os.getenv('hotels_pk', 'hotel_id')
hotels_sk = os.getenv('hotels_sk', 'location')
bookings_table = os.getenv('bookings_table', 'hotel-agent-348d2ff0-bookings')
bookings_pk = os.getenv('bookings_pk', 'booking_id')
bookings_sk = os.getenv('bookings_sk', 'emp_id')

# Helper functions
def get_named_parameter(event, name):
    # Print parameters for debugging
    print(f"Looking for parameter: {name}")
    print(f"Available parameters: {event['parameters']}")
    
    # Direct parameter access without using 'name' property
    for param in event['parameters']:
        if param.get('name') == name:
            return param.get('value')
    
    # If we get here, parameter wasn't found
    raise ValueError(f"Required parameter {name} not set")
    
def populate_function_response(event, response_body):
    return {'response': {'actionGroup': event['actionGroup'], 'function': event['function'],
                'functionResponse': {'responseBody': {'TEXT': {'body': str(response_body)}}}}}

def search_hotels(location, check_in_date, check_out_date, guests=1):
    """Searches for available hotels based on location and dates"""
    try:
        if not location:
            return {"status": "Error", "message": "Required parameter location not set"}
        if not check_in_date:
            return {"status": "Error", "message": "Required parameter check_in_date not set"}
        if not check_out_date:
            return {"status": "Error", "message": "Required parameter check_out_date not set"}
            
        table = dynamodb_resource.Table(hotels_table)
        
        # Query for hotels matching the location
        response = table.query(
            KeyConditionExpression=Key(hotels_sk).eq(location)
        )
        
        hotels = response.get('Items', [])
        
        # Filter hotels by availability
        available_hotels = []
        for hotel in hotels:
            # In a real implementation, we would check availability for the specific dates
            # For this example, we'll assume all hotels are available
            if int(hotel.get('rooms_available', 0)) >= int(guests):
                available_hotels.append(hotel)
        
        if not available_hotels:
            return {"status": "No hotels found", "hotels": []}
        
        # Sort hotels by price (lowest first)
        available_hotels.sort(key=lambda x: float(x.get('price_per_night', '999999')))
        
        # Return top 5 cheapest hotels
        top_hotels = available_hotels[:5]
        
        return {
            "status": "Success",
            "hotels": top_hotels,
            "count": len(top_hotels),
            "total_available": len(available_hotels)
        }
    except Exception as e:
        return {"status": "Error", "message": str(e)}

def check_eligibility(emp_id, hotel_id):
    """Checks if an employee is eligible for a specific hotel based on company policy"""
    try:
        # Get hotel details
        hotels_table_obj = dynamodb_resource.Table(hotels_table)
        hotel_response = hotels_table_obj.get_item(
            Key={'hotel_id': hotel_id}
        )
        
        if 'Item' not in hotel_response:
            return {"status": "Error", "message": "Hotel not found"}
        
        hotel = hotel_response['Item']
        hotel_category = hotel.get('category', 'Standard')
        hotel_price = float(hotel.get('price_per_night', 0))
        
        # This would typically call the HR agent to check eligibility
        # For now, we'll implement basic rules:
        # - Standard category: All employees eligible
        # - Premium category: Only Senior and Executive employees eligible
        # - Luxury category: Only Executive employees eligible
        
        # In a real implementation, this would call the HR agent's API
        # For now, we'll simulate with basic rules
        
        # Get employee details (in a real implementation, this would come from HR agent)
        # Here we're simulating employee grades
        employee_grades = {
            "E001": "Senior",
            "E002": "Mid-level",
            "E003": "Junior",
            "E004": "Executive",
            "E005": "Executive"
        }
        
        employee_grade = employee_grades.get(emp_id, "Junior")
        
        eligible = True
        reason = "Eligible for booking"
        
        if hotel_category == "Premium" and employee_grade not in ["Senior", "Executive"]:
            eligible = False
            reason = "Only Senior and Executive employees are eligible for Premium category hotels"
        
        if hotel_category == "Luxury" and employee_grade != "Executive":
            eligible = False
            reason = "Only Executive employees are eligible for Luxury category hotels"
        
        # Price cap based on employee grade
        price_caps = {
            "Junior": 200,
            "Mid-level": 300,
            "Senior": 500,
            "Executive": 1000
        }
        
        if hotel_price > price_caps.get(employee_grade, 200):
            eligible = False
            reason = f"Hotel price exceeds the limit for {employee_grade} grade"
        
        return {
            "status": "Success",
            "eligible": eligible,
            "reason": reason,
            "hotel": hotel
        }
    except Exception as e:
        return {"status": "Error", "message": str(e)}

def book_hotel(emp_id, hotel_id, check_in_date, check_out_date, guests=1):
    """Books a hotel for an employee"""
    try:
        # First check eligibility
        eligibility = check_eligibility(emp_id, hotel_id)
        
        if not eligibility.get("eligible", False):
            return {
                "status": "Error",
                "message": f"Not eligible for this hotel: {eligibility.get('reason')}"
            }
        
        # Generate booking ID
        booking_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        # Get hotel details
        hotel = eligibility.get("hotel", {})
        
        # Calculate total price
        check_in = datetime.strptime(check_in_date, "%Y-%m-%d")
        check_out = datetime.strptime(check_out_date, "%Y-%m-%d")
        nights = (check_out - check_in).days
        price_per_night = float(hotel.get("price_per_night", 0))
        total_price = price_per_night * nights
        
        # Create booking record
        booking = {
            "booking_id": booking_id,
            "emp_id": emp_id,
            "hotel_id": hotel_id,
            "status": "Confirmed",
            "created_at": timestamp,
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
            "guests": guests,
            "nights": nights,
            "hotel_name": hotel.get("name"),
            "location": hotel.get("location"),
            "room_type": hotel.get("room_type", "Standard"),
            "price_per_night": price_per_night,
            "total_price": total_price
        }
        
        # Save booking to DynamoDB
        table = dynamodb_resource.Table(bookings_table)
        table.put_item(Item=booking)
        
        return {
            "status": "Success",
            "booking_id": booking_id,
            "message": "Hotel booked successfully",
            "booking_details": booking
        }
    except Exception as e:
        return {"status": "Error", "message": str(e)}

def generate_booking_document(booking_id):
    """Generates a booking confirmation document and stores it in S3"""
    try:
        # Get booking details
        table = dynamodb_resource.Table(bookings_table)
        response = table.get_item(
            Key={"booking_id": booking_id}
        )
        
        if 'Item' not in response:
            return {"status": "Error", "message": "Booking not found"}
        
        booking = response['Item']
        
        # In a real implementation, this would generate a PDF and upload to S3
        # For this example, we'll just return a simulated S3 URL
        
        document_url = f"https://s3.amazonaws.com/hotel-bookings/{booking_id}.pdf"
        
        return {
            "status": "Success",
            "document_url": document_url,
            "booking_id": booking_id
        }
    except Exception as e:
        return {"status": "Error", "message": str(e)}

def lambda_handler(event, context):
    print(event)
    
    # Name of the function to invoke
    function = event.get('function', '')
    
    # Parameters to invoke function with
    parameters = event.get('parameters', [])
    
    # Set environment variables from event if they exist
    if 'hotels_table' in event:
        os.environ['hotels_table'] = event['hotels_table']
    if 'hotels_pk' in event:
        os.environ['hotels_pk'] = event['hotels_pk']
    if 'hotels_sk' in event:
        os.environ['hotels_sk'] = event['hotels_sk']
    if 'bookings_table' in event:
        os.environ['bookings_table'] = event['bookings_table']
    if 'bookings_pk' in event:
        os.environ['bookings_pk'] = event['bookings_pk']
    if 'bookings_sk' in event:
        os.environ['bookings_sk'] = event['bookings_sk']
    
    # Route to appropriate function
    if function == 'search_hotels':
        try:
            location = get_named_parameter(event, "location")
        except Exception as e:
            print(f"Error getting location parameter: {str(e)}")
            return populate_function_response(event, {"status": "Error", "message": "Required parameter location not set"})
            
        try:
            check_in_date = get_named_parameter(event, "check_in_date")
        except Exception as e:
            print(f"Error getting check_in_date parameter: {str(e)}")
            return populate_function_response(event, {"status": "Error", "message": "Required parameter check_in_date not set"})
            
        try:
            check_out_date = get_named_parameter(event, "check_out_date")
        except Exception as e:
            print(f"Error getting check_out_date parameter: {str(e)}")
            return populate_function_response(event, {"status": "Error", "message": "Required parameter check_out_date not set"})
        
        # Guests is optional
        try:
            guests = get_named_parameter(event, "guests")
        except:
            guests = 1
            
        result = search_hotels(location, check_in_date, check_out_date, guests)
    elif function == 'check_eligibility':
        emp_id = get_named_parameter(event, "emp_id")
        hotel_id = get_named_parameter(event, "hotel_id")
        result = check_eligibility(emp_id, hotel_id)
    elif function == 'book_hotel':
        emp_id = get_named_parameter(event, "emp_id")
        hotel_id = get_named_parameter(event, "hotel_id")
        check_in_date = get_named_parameter(event, "check_in_date")
        check_out_date = get_named_parameter(event, "check_out_date")
        
        # Guests is optional
        try:
            guests = get_named_parameter(event, "guests")
        except:
            guests = 1
            
        result = book_hotel(emp_id, hotel_id, check_in_date, check_out_date, guests)
    elif function == 'generate_booking_document':
        booking_id = get_named_parameter(event, "booking_id")
        result = generate_booking_document(booking_id)
    else:
        result = f"Error: Function '{function}' not recognized"

    # Format and return the response
    response = populate_function_response(event, result)
    print(response)
    return response