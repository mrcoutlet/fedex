import requests
import base64
import json
from flask import Flask, request, jsonify
from flask_cors import CORS # Used to handle Cross-Origin Resource Sharing

app = Flask(__name__)
CORS(app) # Enable CORS for all routes, allowing your HTML to make requests

# --- Configuration ---
# IMPORTANT: For production, store these in environment variables (e.g., using python-dotenv)
# and NOT directly in your code. This is for demonstration purposes only.
SHIPSTATION_API_KEY = "04ecad55e63a4791b2682ed5dbd9b32d"
SHIPSTATION_API_SECRET = "7c8af0e108214493879c03e6d195295b"

# ShipStation API Base URL
SHIPSTATION_API_BASE_URL = "https://ssapi.shipstation.com/"

# --- Authentication Helper ---
def get_auth_header(api_key, api_secret):
    """
    Generates the Basic Authentication header required by ShipStation API.
    """
    credentials = f"{api_key}:{api_secret}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    return {"Authorization": f"Basic {encoded_credentials}"}

# --- ShipStation API Interaction Function (adapted for backend) ---
def calculate_shipping_fee_from_shipstation(payload_data):
    """
    Sends a request to ShipStation's API to calculate a shipping fee.
    This function is called by the Flask endpoint.
    """
    headers = get_auth_header(SHIPSTATION_API_KEY, SHIPSTATION_API_SECRET)
    headers["Content-Type"] = "application/json"

    # Extracting data safely from frontend payload with default empty dictionaries
    # to prevent KeyError if a top-level key is missing.
    from_address_data = payload_data.get("from", {})
    to_address_data = payload_data.get("to", {})
    package_data = payload_data.get("package", {})
    weight_data = package_data.get("weight", {})
    dimensions_data = package_data.get("dimensions", {})

    # Construct the request payload specifically for ShipStation API's /shipments/getrates endpoint.
    # We explicitly include all expected fields with default values to ensure they are always present,
    # satisfying ShipStation's strict validation for required fields.
    shipstation_payload = {
        "carrierCode": payload_data.get("carrierCode", ""),
        "serviceCode": payload_data.get("serviceCode", ""),
        "fromAddress": {
            "name": from_address_data.get("name", ""),
            "street1": from_address_data.get("street1", ""),
            "city": from_address_data.get("city", ""),
            "state": from_address_data.get("state", ""),
            "postalCode": from_address_data.get("postalCode", ""),
            "country": from_address_data.get("country", "").strip(), # Ensures 'country' is always present and trimmed
            "residential": from_address_data.get("residential", False)
        },
        "toAddress": {
            "name": to_address_data.get("name", ""),
            "street1": to_address_data.get("street1", ""),
            "city": to_address_data.get("city", ""),
            "state": to_address_data.get("state", ""),
            "postalCode": to_address_data.get("postalCode", ""),
            "country": to_address_data.get("country", "").strip(), # Ensures 'country' is always present and trimmed
            "residential": to_address_data.get("residential", False)
        },
        "package": {
            "weight": {
                "value": weight_data.get("value", 0.0), # Ensures 'value' is always present
                "units": weight_data.get("units", "pounds") # Ensures 'units' is always present
            },
            "dimensions": {
                "length": dimensions_data.get("length", 0.0),
                "width": dimensions_data.get("width", 0.0),
                "height": dimensions_data.get("height", 0.0),
                "units": dimensions_data.get("units", "inches")
            },
            "packageType": package_data.get("packageType", "package"),
            "insuredValue": package_data.get("insuredValue", 0.0),
            "contents": package_data.get("contents", "")
        },
        "testMode": payload_data.get("testMode", False)
    }

    api_endpoint = f"{SHIPSTATION_API_BASE_URL}shipments/getrates"

    print(f"\n[Backend] Attempting to send request to: {api_endpoint}")
    print(f"[Backend] Request Payload: {json.dumps(shipstation_payload, indent=2)}")

    try:
        response = requests.post(api_endpoint, headers=headers, data=json.dumps(shipstation_payload))
        response.raise_for_status()  # Raises HTTPError for bad responses (4xx or 5xx)

        response_data = response.json()
        print(f"\n[Backend] ShipStation API Response (Success): {json.dumps(response_data, indent=2)}")

        # --- Parse the response ---
        # The /shipments/getrates endpoint returns a list of rates, even if only one is requested.
        if response_data and isinstance(response_data, list) and len(response_data) > 0:
            # We'll take the first rate found for simplicity
            first_rate = response_data[0]
            shipping_cost = first_rate.get("shipmentCost")
            other_charges = first_rate.get("otherCost", 0.0) # Default to 0 if not present
            total_fee = shipping_cost + other_charges if shipping_cost is not None else None

            if total_fee is not None:
                print(f"[Backend] Calculated Shipping Cost: ${shipping_cost:.2f}")
                print(f"[Backend] Other Charges: ${other_charges:.2f}")
                print(f"Total Estimated Fee: ${total_fee:.2f}")
                return {"success": True, "fee": total_fee, "details": first_rate}
            else:
                return {"success": False, "message": "Could not extract total fee from response."}
        elif response_data and "errors" in response_data:
            print(f"[Backend] ShipStation API Error: {response_data['errors']}")
            return {"success": False, "message": f"ShipStation API Error: {response_data['errors']}"}
        else:
            print("[Backend] Could not find shipping fee in the response or unexpected structure.")
            return {"success": False, "message": "Unexpected response structure from ShipStation API."}

    except requests.exceptions.HTTPError as http_err:
        error_message = f"HTTP error occurred: {http_err}. Response: {response.text}"
        print(f"[Backend] {error_message}")
        return {"success": False, "message": error_message}
    except requests.exceptions.ConnectionError as conn_err:
        error_message = f"Connection error occurred: {conn_err}"
        print(f"[Backend] {error_message}")
        return {"success": False, "message": error_message}
    except requests.exceptions.Timeout as timeout_err:
        error_message = f"Timeout error occurred: {timeout_err}"
        print(f"[Backend] {error_message}")
        return {"success": False, "message": error_message}
    except requests.exceptions.RequestException as req_err:
        error_message = f"An unexpected request error occurred: {req_err}"
        print(f"[Backend] {error_message}")
        return {"success": False, "message": error_message}
    except json.JSONDecodeError:
        error_message = f"Failed to decode JSON response from ShipStation: {response.text}"
        print(f"[Backend] {error_message}")
        return {"success": False, "message": error_message}
    except Exception as e:
        error_message = f"An unhandled error occurred in backend: {e}"
        print(f"[Backend] {error_message}")
        return {"success": False, "message": e}


# --- Flask Route for Shipping Calculation ---
@app.route('/calculate-shipping', methods=['POST'])
def calculate_shipping():
    """
    Flask endpoint to receive shipping details from the frontend,
    call ShipStation API, and return the calculated fee.
    """
    if not request.is_json:
        return jsonify({"success": False, "message": "Request must be JSON"}), 400

    data = request.get_json()
    print(f"\n[Backend] Received data from frontend: {json.dumps(data, indent=2)}")

    # The payload from frontend is a single object. Pass it directly to the ShipStation interaction function.
    shipment_payload = data 

    result = calculate_shipping_fee_from_shipstation(shipment_payload)

    if result["success"]:
        return jsonify({"success": True, "fee": result["fee"], "details": result["details"]}), 200
    else:
        return jsonify({"success": False, "message": result["message"]}), 500

# --- Run the Flask App ---
if __name__ == '__main__':
    # For development, run on localhost:5000
    # In a production environment, you would use a WSGI server like Gunicorn or uWSGI
    print("\n--- Starting Flask Backend ---")
    print("Access the frontend HTML file and ensure it points to http://127.0.0.1:5000")
    print("This server will listen for requests on http://127.0.0.1:5000/calculate-shipping")
    app.run(debug=True, port=5000)
