import boto3
import json
import os
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key, Attr

# Initialize DynamoDB resources
dynamodb_resource = boto3.resource('dynamodb')
dynamodb_table = os.getenv('dynamodb_table')
dynamodb_pk = os.getenv('dynamodb_pk')
dynamodb_sk = os.getenv('dynamodb_sk')

approval_requests_table = os.getenv('approval_requests_table')
approval_pk = os.getenv('approval_pk')
approval_sk = os.getenv('emp_id')
# Helper functions
def get_named_parameter(event, name):
    return next(item for item in event['parameters'] if item['name'] == name)['value']
    
def populate_function_response(event, response_body):
    return {'response': {'actionGroup': event['actionGroup'], 'function': event['function'],
                'functionResponse': {'responseBody': {'TEXT': {'body': str(response_body)}}}}}

def read_dynamodb(table_name, pk_field, pk_value, filter_key=None, filter_value=None):
    try:
        table = dynamodb_resource.Table(table_name)
        key_expression = Key(pk_field).eq(pk_value)
        
        if filter_key:
            filter_expression = Attr(filter_key).eq(filter_value)
            query_data = table.query(
                KeyConditionExpression=key_expression,
                FilterExpression=filter_expression
            )
        else:
            query_data = table.query(
                KeyConditionExpression=key_expression
            )
        
        return query_data['Items']
    except Exception as e:
        print(f'Error querying table: {table_name}. Error: {str(e)}')
        return []

def update_dynamodb(table_name, pk_field, pk_value, update_field, update_value):
    try:
        table = dynamodb_resource.Table(table_name)
        response = table.update_item(
            Key={pk_field: pk_value},
            UpdateExpression=f"set {update_field} = :val",
            ExpressionAttributeValues={':val': update_value},
            ReturnValues="UPDATED_NEW"
        )
        return response
    except Exception as e:
        print(f'Error updating table: {table_name}. Error: {str(e)}')
        return None

# Core HR functions
def get_employee_info(emp_id):
    """Retrieves employee details including grade, department, and manager"""
    employee_data = read_dynamodb(dynamodb_table, dynamodb_pk, emp_id)
    
    if not employee_data:
        return f"No employee found with ID: {emp_id}"
    
    # Remove sensitive fields before returning
    employee = employee_data[0]
    if 'emergency_contact' in employee:
        del employee['emergency_contact']
    
    return employee

def get_travel_preferences(emp_id):
    """Retrieves employee's travel preferences and requirements"""
    employee_data = read_dynamodb(dynamodb_table, dynamodb_pk, emp_id)
    
    if not employee_data:
        return f"No employee found with ID: {emp_id}"
    
    # Extract only travel-related preferences
    travel_fields = ['preferred_airlines', 'dietary_restrictions', 'accessibility_needs']
    travel_preferences = {k: employee_data[0].get(k, 'Not specified') for k in travel_fields}
    
    return travel_preferences

def validate_travel_request(emp_id, destination, duration, cost):
    """Checks if a travel request complies with company policy"""
    employee_data = read_dynamodb(dynamodb_table, dynamodb_pk, emp_id)
    
    if not employee_data:
        return f"No employee found with ID: {emp_id}"
    
    employee = employee_data[0]
    grade = employee.get('grade', '')
    budget_remaining = float(employee.get('travel_budget_remaining', 0))
    
    # Policy validation logic
    validation_results = {
        "valid": True,
        "issues": [],
        "budget_sufficient": budget_remaining >= float(cost)
    }
    
    # Check budget
    if float(cost) > budget_remaining:
        validation_results["valid"] = False
        validation_results["issues"].append(f"Insufficient budget: {budget_remaining} remaining, {cost} requested")
    
    # Check duration limits by grade
    max_duration = {"Junior": 5, "Mid-level": 7, "Senior": 10, "Executive": 14}
    if int(duration) > max_duration.get(grade, 5):
        validation_results["valid"] = False
        validation_results["issues"].append(f"Duration exceeds limit for {grade} grade: {duration} days requested, {max_duration.get(grade, 5)} allowed")
    
    # Check high-risk destinations (simplified example)
    high_risk_destinations = ["Country A", "Country B", "Country C"]
    if destination in high_risk_destinations:
        validation_results["valid"] = False
        validation_results["issues"].append(f"Destination {destination} requires special approval")
    
    return validation_results

def get_approval_requirements(emp_id, destination, duration, cost):
    """Determines approval workflow based on destination, duration, and cost"""
    employee_data = read_dynamodb(dynamodb_table, dynamodb_pk, emp_id)
    
    if not employee_data:
        return f"No employee found with ID: {emp_id}"
    
    employee = employee_data[0]
    grade = employee.get('grade', '')
    default_approval = employee.get('approval_level', 'Manager')
    
    # Determine approval level based on various factors
    approval_level = default_approval
    
    # Cost thresholds by grade
    cost_thresholds = {
        "Junior": 1000,
        "Mid-level": 2000,
        "Senior": 5000,
        "Executive": 10000
    }
    
    # Duration thresholds
    if int(duration) > 7:
        approval_level = "Director"
    
    # Cost thresholds
    if float(cost) > cost_thresholds.get(grade, 1000):
        approval_level = "Director"
    
    if float(cost) > 10000:
        approval_level = "VP"
    
    # International travel always requires higher approval
    international_destinations = ["Country X", "Country Y", "Country Z"]  # Example list
    if destination in international_destinations:
        if approval_level == "Manager":
            approval_level = "Director"
    
    return {
        "approval_required": approval_level,
        "manager_id": employee.get('manager_id', 'Unknown'),
        "estimated_approval_time": "24-48 hours" if approval_level == "Manager" else "3-5 business days"
    }

def check_passport_status(emp_id):
    """Verifies if employee's passport is valid for international travel"""
    employee_data = read_dynamodb(dynamodb_table, dynamodb_pk, emp_id)
    
    if not employee_data:
        return f"No employee found with ID: {emp_id}"
    
    employee = employee_data[0]
    passport_status = employee.get('passport_status', 'Unknown')
    passport_expiry = employee.get('passport_expiry', 'Unknown')
    
    # Check if passport is expiring soon (within 6 months)
    if passport_expiry != 'Unknown':
        try:
            expiry_date = datetime.strptime(passport_expiry, '%Y-%m-%d')
            six_months_from_now = datetime.now() + timedelta(days=180)
            
            if expiry_date < datetime.now():
                passport_status = "Expired"
            elif expiry_date < six_months_from_now:
                passport_status = "Expiring Soon"
        except:
            pass
    
    return {
        "passport_status": passport_status,
        "passport_expiry": passport_expiry,
        "valid_for_international_travel": passport_status == "Valid",
        "nationality": employee.get('nationality', 'Unknown')
    }


def create_approval_request(emp_id, manager_id, request_type, details, approval_level):
    """Creates a new approval request in the system"""
    request_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()
    
    item = {
        'request_id': request_id,
        'emp_id': emp_id,
        'manager_id': manager_id,
        'request_type': request_type,  # e.g., "hotel", "flight", "car"
        'details': details,            # JSON string with booking details
        'approval_level': approval_level,  # "Self", "Manager", "Director", "VP"
        'status': 'Pending',
        'created_at': timestamp,
        'updated_at': timestamp
    }
    
    table = dynamodb_resource.Table(approval_requests_table)
    table.put_item(Item=item)
    
    return {
        "request_id": request_id,
        "status": "Pending",
        "message": f"Approval request created and pending {approval_level} approval"
    }

def check_approval_status(request_id, emp_id):
    """Checks the status of an approval request"""
    table = dynamodb_resource.Table(approval_requests_table)
    response = table.get_item(
        Key={
            'request_id': request_id,
            'emp_id': emp_id
        }
    )
    
    if 'Item' not in response:
        return {"status": "Not Found", "message": "Approval request not found"}
    
    return {
        "status": response['Item']['status'],
        "approval_level": response['Item']['approval_level'],
        "details": response['Item']['details'],
        "created_at": response['Item']['created_at'],
        "updated_at": response['Item']['updated_at']
    }

def approve_request(request_id, emp_id, approver_id):
    """Approves a pending request"""
    # First check if the approver is authorized
    table = dynamodb_resource.Table(approval_requests_table)
    response = table.get_item(
        Key={
            'request_id': request_id,
            'emp_id': emp_id
        }
    )
    
    if 'Item' not in response:
        return {"status": "Error", "message": "Request not found"}
    
    request = response['Item']
    
    # For self-approval, the approver must be the employee
    if request['approval_level'] == 'Self' and approver_id != emp_id:
        return {"status": "Error", "message": "Unauthorized approval attempt"}
    
    # For manager approval, check if approver is the manager
    if request['approval_level'] != 'Self' and approver_id != request['manager_id']:
        # Here you would check if the approver is a Director or VP if needed
        # This would require looking up the approver's role in the employee table
        employee_table = dynamodb_resource.Table(dynamodb_table)
        approver_data = employee_table.get_item(
            Key={'emp_id': approver_id}
        )
        
        if 'Item' not in approver_data or approver_data['Item']['grade'] not in ['Director', 'Executive']:
            return {"status": "Error", "message": "Unauthorized approval attempt"}
    
    # Update the request status
    timestamp = datetime.now().isoformat()
    table.update_item(
        Key={
            'request_id': request_id,
            'emp_id': emp_id
        },
        UpdateExpression="set #status = :s, approver_id = :a, updated_at = :u",
        ExpressionAttributeNames={
            '#status': 'status'
        },
        ExpressionAttributeValues={
            ':s': 'Approved',
            ':a': approver_id,
            ':u': timestamp
        }
    )
    
    return {
        "status": "Approved",
        "message": f"Request {request_id} has been approved by {approver_id}",
        "updated_at": timestamp
    }

def list_pending_approvals(approver_id):
    """Lists all pending approvals for a manager"""
    table = dynamodb_resource.Table(approval_requests_table)
    
    # Query for requests where this person is the manager and status is Pending
    response = table.scan(
        FilterExpression="manager_id = :m AND #status = :s",
        ExpressionAttributeNames={
            '#status': 'status'
        },
        ExpressionAttributeValues={
            ':m': approver_id,
            ':s': 'Pending'
        }
    )
    
    return response['Items']

def lambda_handler(event, context):
    print(event)
    
    # Name of the function to invoke
    function = event.get('function', '')
    
    # Parameters to invoke function with
    parameters = event.get('parameters', [])
    
    # Route to appropriate function
    if function == 'get_employee_info':
        emp_id = get_named_parameter(event, "emp_id")
        result = get_employee_info(emp_id)
    elif function == 'get_travel_preferences':
        emp_id = get_named_parameter(event, "emp_id")
        result = get_travel_preferences(emp_id)
    elif function == 'validate_travel_request':
        emp_id = get_named_parameter(event, "emp_id")
        destination = get_named_parameter(event, "destination")
        duration = get_named_parameter(event, "duration")
        cost = get_named_parameter(event, "cost")
        result = validate_travel_request(emp_id, destination, duration, cost)
    elif function == 'get_approval_requirements':
        emp_id = get_named_parameter(event, "emp_id")
        destination = get_named_parameter(event, "destination")
        duration = get_named_parameter(event, "duration")
        cost = get_named_parameter(event, "cost")
        result = get_approval_requirements(emp_id, destination, duration, cost)
    elif function == 'check_passport_status':
        emp_id = get_named_parameter(event, "emp_id")
        result = check_passport_status(emp_id)
    # New approval workflow functions
    elif function == 'create_approval_request':
        emp_id = get_named_parameter(event, "emp_id")
        request_type = get_named_parameter(event, "request_type")
        details = get_named_parameter(event, "details")
        
        # Get employee info to determine manager and approval level
        employee_info = get_employee_info(emp_id)
        manager_id = employee_info.get('manager_id', 'None')
        approval_level = employee_info.get('approval_level', 'Manager')
        
        result = create_approval_request(emp_id, manager_id, request_type, details, approval_level)
    elif function == 'check_approval_status':
        request_id = get_named_parameter(event, "request_id")
        emp_id = get_named_parameter(event, "emp_id")
        result = check_approval_status(request_id, emp_id)
    elif function == 'approve_request':
        request_id = get_named_parameter(event, "request_id")
        emp_id = get_named_parameter(event, "emp_id")
        approver_id = get_named_parameter(event, "approver_id")
        result = approve_request(request_id, emp_id, approver_id)
    elif function == 'list_pending_approvals':
        approver_id = get_named_parameter(event, "approver_id")
        result = list_pending_approvals(approver_id)
    else:
        result = f"Error: Function '{function}' not recognized"

    # Format and return the response
    response = populate_function_response(event, result)
    print(response)
    return response
