from flask import Flask, request, jsonify
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import re
import time

app = Flask(__name__)


def format_awrs(urn: str) -> str:
    """Ensure format 'XXXX dddd dddd ddd'."""
    u = re.sub(r"[^A-Za-z0-9]", "", (urn or "").upper())
    if len(u) == 15 and u[:4].isalpha() and u[4:].isdigit():
        return f"{u[:4]} {u[4:8]} {u[8:12]} {u[12:]}"
    return (urn or "").strip().upper()


def normalise_status(raw: str) -> str:
    """Match desktop script behaviour."""
    s = (raw or "").strip().lower()
    if s == "approved":
        return "Approved"
    if s in {"not approved", "no longer approved", "no-longer approved"}:
        return "Not Approved"
    if s in {"no match", "no results found"}:
        return "No Match"
    if s in {"deregistered", "removed", "revoked", "application withdrawn"}:
        return "Deregistered"
    if s == "not applicable":
        return "Approved"  # This is key!
    if not s or s == "":
        return "Unknown"
    return (raw or "").strip()


def find_after_label(label: str, soup) -> str:
    """Find data after a specific label in HTML, similar to your desktop script logic."""
    try:
        # Look for dt/dd pairs (definition lists)
        for dt in soup.find_all('dt'):
            if dt.get_text().strip().lower() == label.lower():
                dd = dt.find_next_sibling('dd')
                if dd:
                    return ' '.join(dd.get_text().split()).strip()

        # Look for label: value patterns
        text = soup.get_text()
        pattern = rf"{re.escape(label)}\s*:?\s*([^\n\r]+)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Look for label followed by content on next line
        pattern = rf"{re.escape(label)}\s*\n\s*([^\n\r]+)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        return ""
    except Exception:
        return ""


def lookup_single_awrs(awrs_number: str, supplier_name: str = "") -> dict:
    """Look up AWRS using requests + BeautifulSoup (Replit compatible)."""
    try:
        print(
            f"[{datetime.now()}] Looking up AWRS: {awrs_number} for {supplier_name}"
        )

        HMRC_URL = "https://www.tax.service.gov.uk/check-the-awrs-register"

        # Create session with proper headers
        session = requests.Session()
        session.headers.update({
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept':
            'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-GB,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

        # Get the main page
        print(f"[DEBUG] Getting main page: {HMRC_URL}")
        response = session.get(HMRC_URL, timeout=10)

        if response.status_code != 200:
            return {
                "success": False,
                "status": "Error",
                "error":
                f"Failed to access HMRC website: {response.status_code}",
                "business_name": "",
                "address": "",
                "deregistration_date": "",
                "effective_date": "",
                "urn": "",
                "awrs_number": awrs_number,
                "supplier_name": supplier_name,
                "search_timestamp": datetime.now().strftime("%d %B %Y %I:%M%p")
            }

        soup = BeautifulSoup(response.content, 'html.parser')

        # Look for "Check a URN" link/form
        check_urn_url = None
        for link in soup.find_all(['a', 'form']):
            if link.get_text() and 'check a urn' in link.get_text().lower():
                check_urn_url = link.get('href') or link.get('action')
                break

        # If we found a specific check URN endpoint, use it
        if check_urn_url and not check_urn_url.startswith('http'):
            check_urn_url = 'https://www.tax.service.gov.uk' + check_urn_url
            print(f"[DEBUG] Found check URN URL: {check_urn_url}")
            response = session.get(check_urn_url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')

        # Find the search form
        form = soup.find('form')
        if not form:
            return {
                "success": False,
                "status": "Error",
                "error": "Could not find search form on HMRC website",
                "business_name": "",
                "address": "",
                "deregistration_date": "",
                "effective_date": "",
                "urn": "",
                "awrs_number": awrs_number,
                "supplier_name": supplier_name,
                "search_timestamp": datetime.now().strftime("%d %B %Y %I:%M%p")
            }

        # Build form data
        form_data = {}

        # Extract hidden fields
        for hidden_input in soup.find_all('input', {'type': 'hidden'}):
            name = hidden_input.get('name')
            value = hidden_input.get('value', '')
            if name:
                form_data[name] = value

        # Find text input field
        text_input = None
        for selector in [
                'input[name="value"]', 'input[name="query"]',
                'input[type="text"]'
        ]:
            inputs = soup.select(selector)
            if inputs:
                text_input = inputs[0]
                break

        if not text_input:
            return {
                "success": False,
                "status": "Error",
                "error": "Could not find text input field",
                "business_name": "",
                "address": "",
                "deregistration_date": "",
                "effective_date": "",
                "urn": "",
                "awrs_number": awrs_number,
                "supplier_name": supplier_name,
                "search_timestamp": datetime.now().strftime("%d %B %Y %I:%M%p")
            }

        # Format AWRS number and add to form data
        formatted_urn = format_awrs(awrs_number)
        form_data[text_input.get('name')] = formatted_urn

        print(f"[DEBUG] Submitting search for: {formatted_urn}")

        # Submit the form
        action_url = form.get('action', '')
        if not action_url.startswith('http'):
            action_url = 'https://www.tax.service.gov.uk' + action_url

        # Small delay
        time.sleep(0.5)

        # Submit search
        search_response = session.post(action_url, data=form_data, timeout=15)

        if search_response.status_code != 200:
            return {
                "success": False,
                "status": "Error",
                "error":
                f"Search failed with status: {search_response.status_code}",
                "business_name": "",
                "address": "",
                "deregistration_date": "",
                "effective_date": "",
                "urn": "",
                "awrs_number": awrs_number,
                "supplier_name": supplier_name,
                "search_timestamp": datetime.now().strftime("%d %B %Y %I:%M%p")
            }

        # Parse results
        result_soup = BeautifulSoup(search_response.content, 'html.parser')

        # Extract data using similar logic to your desktop script
        business_name = find_after_label("Business name", result_soup)
        status = (find_after_label("Status", result_soup)
                  or find_after_label("Application status", result_soup)
                  or find_after_label("Registration status", result_soup))

        address = (find_after_label("Principal place of business", result_soup)
                   or find_after_label("Business address", result_soup)
                   or find_after_label("Address", result_soup))

        deregistration_date = find_after_label("Date of deregistration",
                                               result_soup)
        effective_date = (
            find_after_label("Effective date of registration", result_soup)
            or find_after_label("Registration date", result_soup))

        urn = (find_after_label("URN", result_soup)
               or find_after_label("AWRS URN", result_soup))

        # Debug logging
        print(f"[DEBUG] Extracted data:")
        print(f"  Business name: '{business_name}'")
        print(f"  Status: '{status}'")
        print(f"  Address: '{address}'")
        print(f"  Deregistration date: '{deregistration_date}'")
        print(f"  Effective date: '{effective_date}'")
        print(f"  URN: '{urn}'")

        # Apply status normalization
        if status:
            status = normalise_status(status)

        # Handle "not applicable" cases
        if deregistration_date and deregistration_date.strip().lower(
        ) == "not applicable":
            deregistration_date = ""
            if not status or status == "Unknown":
                status = "Approved"

        # Generate timestamp
        search_timestamp = datetime.now().strftime("%d %B %Y %I:%M%p")

        result = {
            "success": True,
            "status": status or "Unknown",
            "business_name": business_name or "Not found",
            "address": address or "",
            "deregistration_date": deregistration_date or "",
            "effective_date": effective_date or "",
            "urn": urn or formatted_urn,
            "awrs_number": awrs_number,
            "supplier_name": supplier_name,
            "search_timestamp": search_timestamp
        }

        print(f"[{datetime.now()}] ✓ Lookup complete")
        print(
            f"[RESULT] Status: {result['status']}, Business: {result['business_name']}"
        )

        return result

    except Exception as e:
        print(f"[{datetime.now()}] ✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()

        return {
            "success": False,
            "status": "Error",
            "error": f"Error during AWRS lookup: {str(e)}",
            "business_name": "",
            "address": "",
            "deregistration_date": "",
            "effective_date": "",
            "urn": "",
            "awrs_number": awrs_number,
            "supplier_name": supplier_name,
            "search_timestamp": datetime.now().strftime("%d %B %Y %I:%M%p")
        }


@app.route('/', methods=['POST'])
def webhook_handler():
    """Handle webhook from Zapier"""
    try:
        data = request.json or {}
        awrs_number = data.get('awrs_number', '').strip()
        supplier_name = data.get('supplier_name', '')

        print(f"[WEBHOOK] Received request for AWRS: {awrs_number}")

        if not awrs_number:
            return jsonify({
                'success':
                False,
                'status':
                'Error',
                'error':
                'No AWRS number provided',
                'business_name':
                '',
                'address':
                '',
                'deregistration_date':
                '',
                'effective_date':
                '',
                'urn':
                '',
                'search_timestamp':
                datetime.now().strftime("%d %B %Y %I:%M%p")
            })

        # Call AWRS lookup function
        result = lookup_single_awrs(awrs_number, supplier_name)

        print(f"[WEBHOOK] Returning result: {result}")
        return jsonify(result)

    except Exception as e:
        print(f"[WEBHOOK] Error: {str(e)}")
        return jsonify({
            'success':
            False,
            'status':
            'Error',
            'error':
            str(e),
            'business_name':
            '',
            'address':
            '',
            'deregistration_date':
            '',
            'effective_date':
            '',
            'urn':
            '',
            'search_timestamp':
            datetime.now().strftime("%d %B %Y %I:%M%p")
        })


@app.route('/', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'AWRS REQUESTS-BASED API is running',
        'timestamp': datetime.now().isoformat()
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
