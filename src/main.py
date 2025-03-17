from apify import Actor
import os
import requests
import pandas as pd
import pdfplumber
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# Set up the session
session = requests.Session()
base_url = "https://central.phims.org/Mchenry/Result.aspx"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Referer': base_url
}

session.headers.update(headers)

# Define search queries
search_queries = ["Alg", "Bar", "Car", "Gro", "Hil", "hun", "joh", "Lake", "mar", "mch", "ric", "rin", "uni", "val", "woo"]
all_data = []

last_month = datetime.now() - timedelta(days=30)

async def main():
    async with Actor:
        for query in search_queries:
            print(f"🔎 Searching for: {query}")

            response = session.get(base_url)
            soup = BeautifulSoup(response.text, "html.parser")

            # Extract hidden ASP.NET form fields
            viewstate = soup.find("input", {"name": "__VIEWSTATE"}).get("value")
            event_validation = soup.find("input", {"name": "__EVENTVALIDATION"}).get("value")

            search_payload = {
                "__VIEWSTATE": viewstate,
                "__EVENTVALIDATION": event_validation,
                "txtSearch": query,
                "BtnSearch": "Search"
            }

            response = session.post(base_url, data=search_payload)
            soup = BeautifulSoup(response.text, "html.parser")

            viewstate = soup.find("input", {"name": "__VIEWSTATE"}).get("value")
            event_validation = soup.find("input", {"name": "__EVENTVALIDATION"}).get("value")
            # Step 3: Extract the inspection data
            rows = soup.find_all("tr")[2:]  # Skip header rows

            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 7:
                    continue

                establishment = cols[2].text.strip()
                site = cols[3].text.strip()
                address = cols[4].text.strip()
                date_object = cols[6].text.strip()
                try:
                    inspection_date = datetime.strptime(date_object, '%m/%d/%Y')
                except ValueError:
                    continue
            
                # Only process entries from the last month
                if inspection_date and inspection_date < last_month:
                    break

                # Step 4: Find the "View" button and trigger PDF download
                view_button = cols[1].find("input", {"type": "submit"})
                if view_button:
                    pdf_payload = {
                        "__VIEWSTATE": viewstate,
                        "__EVENTVALIDATION": event_validation,
                        view_button["name"]: view_button["value"]
                    }

                    pdf_response = session.post(base_url, data=pdf_payload, stream=True)
                    content_type = pdf_response.headers.get("Content-Type", "")

                    if "application/pdf" in content_type.lower():
                        safe_establishment = re.sub(r'[<>:"/\\|?*]', '_', establishment)
                        inspection_date_safe = inspection_date.strftime('%Y-%m-%d')
                        pdf_filename = f"InspectionReport_{safe_establishment.replace(' ', '_')}_{inspection_date_safe}.pdf"

                        with open(pdf_filename, "wb") as f:
                            f.write(pdf_response.content)
                        print(f"✅ Downloaded: {pdf_filename}")

                        # Extract text and permit holder details
                        permit_holder, violation_comments = "", []
                        city, person_in_charge = "", ""
                        cities = ['ALGONQUIN', 'WOODSTOCK', 'CRYSTAL LAKE', 'LAKE IN THE HILLS', 'HUNTLEY', 'FOX LAKE', 'ISLAND LAKE', 'MARENGO', 'MCHENRY', 'HARVARD']
                        with pdfplumber.open(pdf_filename) as pdf:
                            for page in pdf.pages:
                                text = page.extract_text()
                                if text:
                                    lines = text.split("\n")
                                    for i, line in enumerate(lines):
                                        if "permit holder" in line.lower():
                                            if i + 1 < len(lines) and "Purpose of Inspection" not in lines[i + 1]:
                                                raw_holder = lines[i + 1].strip()
                                                cleaned_holder = raw_holder[9:].strip()  # Remove first 9 characters
                                                cleaned_holder = re.sub(r"\s+Risk\s+Classification\s+[IVX]+$", "", cleaned_holder)
                                                cleaned_holder = re.sub(r"\s+(Full|Complaint|Farmers Market|Winter Market|Partial|Opening|Closure|Training|Re-inspection|Pre-inspection)$", "", cleaned_holder)
                                                
                                                permit_holder = cleaned_holder
                                        if "city" in line.lower() and i + 1 < len(lines):
                                            raw_city = lines[i + 1].strip()
                                            if raw_city:
                                                for city_item in cities:
                                                    if city_item in raw_city.upper():
                                                        city = city_item
                                                        print("city:", city)
                                                        break
                                                    else:
                                                        continue
                                        if "person in charge (signature)" in line.lower() and i + 1 < len(lines):
                                            raw_person_item = lines[i - 1].strip()
                                            raw_person = raw_person_item.split()[:-1]
                                            person_in_charge = ' '.join(raw_person)
                                            print("person_in_charge:", person_in_charge)
                                        if "gasket" in line.lower():
                                            violation_comments.append(line.strip())

                        os.remove(pdf_filename)  # Clean up by deleting the PDF
                        if violation_comments and len(violation_comments) > 0:
                            await Actor.push_data(
                            {
                                "Establishment": establishment,
                                "Site": site,
                                "Address": address,
                                "City": city,
                                "Person in Charge": person_in_charge,
                                "Inspection Date": inspection_date_safe,
                                "Permit Holder": permit_holder,
                                "Gasket Violations": "; ".join(violation_comments)
                            }
                        )
        print("Scraping completed!")
