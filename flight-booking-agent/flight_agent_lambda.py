import boto3
import json
import os
import uuid
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key, Attr
from decimal import Decimal

# Initialize DynamoDB resources
dynamodb_resource = boto3.resource('dynamodb')
flights_table = os.getenv('flights_table')
flights_pk = os.getenv('flights_pk')
flights_sk = os.getenv('flights_sk')
bookings_table = os.getenv('bookings_table')
bookings_pk = os.getenv('bookings_pk')
bookings_sk = os.getenv('bookings_sk')

# Helper functions
def get_named_parameter(event, name):
    return next(item for item in event['parameters'] if item['name'] == name)['value']
    
def populate_function_response(event, response_body):
    return {'response': {'actionGroup': event['actionGroup'], 'function': event['function'],
                'functionResponse': {'responseBody': {'TEXT': {'body': str(response_body)}}}}}

def search_flights(origin, destination, departure_date, return_date=None):
    """Searches for available flights based on origin, destination and dates"""
    try:
        table = dynamodb_resource.Table(flights_table)
        
        # Create the route string (used as sort key)
        route = f"{origin}-{destination}"
        
        # Query for flights matching the route
        response = table.query(
            KeyConditionExpression=Key(flights_sk).eq(route)
        )
        
        flights = response.get('Items', [])
        
        # Filter flights by departure date
        matching_flights = []
        for flight in flights:
            flight_date = flight.get('departure_date')
            if flight_date == departure_date:
                matching_flights.append(flight)
        
        if not matching_flights:
            return {"status": "No flights found", "flights": []}
        
        # Sort flights by price (lowest first)
        matching_flights.sort(key=lambda x: float(x.get('price', '999999')))
        
        # Return top 5 cheapest flights
        top_flights = matching_flights[:5]
        
        return {
            "status": "Success",
            "flights": top_flights,
            "count": len(top_flights),
            "total_available": len(matching_flights)
        }
    except Exception as e:
        return {"status": "Error", "message": str(e)}

def check_eligibility(emp_id, flight_id):
    """Checks if an employee is eligible for a specific flight based on company policy"""
    try:
        # Get flight details
        flights_table_obj = dynamodb_resource.Table(flights_table)
        flight_response = flights_table_obj.get_item(
            Key={'flight_id': flight_id}
        )
        
        if 'Item' not in flight_response:
            return {"status": "Error", "message": "Flight not found"}
        
        flight = flight_response['Item']
        flight_class = flight.get('class', 'Economy')
        flight_price = float(flight.get('price', 0))
        
        # This would typically call the HR agent to check eligibility
        # For now, we'll implement basic rules:
        # - Economy class: All employees eligible
        # - Business class: Only Senior and Executive employees eligible
        # - First class: Only Executive employees eligible
        
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
        
        if flight_class == "Business" and employee_grade not in ["Senior", "Executive"]:
            eligible = False
            reason = "Only Senior and Executive employees are eligible for Business class"
        
        if flight_class == "First" and employee_grade != "Executive":
            eligible = False
            reason = "Only Executive employees are eligible for First class"
        
        # Price cap based on employee grade
        price_caps = {
            "Junior": 1000,
            "Mid-level": 2000,
            "Senior": 5000,
            "Executive": 10000
        }
        
        if flight_price > price_caps.get(employee_grade, 1000):
            eligible = False
            reason = f"Flight price exceeds the limit for {employee_grade} grade"
        
        return {
            "status": "Success",
            "eligible": eligible,
            "reason": reason,
            "flight": flight
        }
    except Exception as e:
        return {"status": "Error", "message": str(e)}

def book_flight(emp_id, flight_id):
    """Books a flight for an employee"""
    try:
        # First check eligibility
        eligibility = check_eligibility(emp_id, flight_id)
        
        if not eligibility.get("eligible", False):
            return {
                "status": "Error",
                "message": f"Not eligible for this flight: {eligibility.get('reason')}"
            }
        
        # Generate booking ID
        booking_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        # Get flight details
        flight = eligibility.get("flight", {})
        
        # Create booking record
        booking = {
            "booking_id": booking_id,
            "emp_id": emp_id,
            "flight_id": flight_id,
            "status": "Confirmed",
            "created_at": timestamp,
            "origin": flight.get("origin"),
            "destination": flight.get("destination"),
            "departure_date": flight.get("departure_date"),
            "departure_time": flight.get("departure_time"),
            "arrival_time": flight.get("arrival_time"),
            "airline": flight.get("airline"),
            "flight_number": flight.get("flight_number"),
            "class": flight.get("class"),
            "price": flight.get("price")
        }
        
        # Save booking to DynamoDB
        table = dynamodb_resource.Table(bookings_table)
        table.put_item(Item=booking)
        
        return {
            "status": "Success",
            "booking_id": booking_id,
            "message": "Flight booked successfully",
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
        
        document_url = f"https://s3.amazonaws.com/flight-bookings/{booking_id}.pdf"
        
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
    
    # Route to appropriate function
    if function == 'search_flights':
        origin = get_named_parameter(event, "origin")
        destination = get_named_parameter(event, "destination")
        departure_date = get_named_parameter(event, "departure_date")
        
        # Return date is optional
        try:
            return_date = get_named_parameter(event, "return_date")
        except:
            return_date = None
            
        result = search_flights(origin, destination, departure_date, return_date)
    elif function == 'check_eligibility':
        emp_id = get_named_parameter(event, "emp_id")
        flight_id = get_named_parameter(event, "flight_id")
        result = check_eligibility(emp_id, flight_id)
    elif function == 'book_flight':
        emp_id = get_named_parameter(event, "emp_id")
        flight_id = get_named_parameter(event, "flight_id")
        result = book_flight(emp_id, flight_id)
    elif function == 'generate_booking_document':
        booking_id = get_named_parameter(event, "booking_id")
        result = generate_booking_document(booking_id)
    else:
        result = f"Error: Function '{function}' not recognized"

    # Format and return the response
    response = populate_function_response(event, result)
    print(response)
    return response
