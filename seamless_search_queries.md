# Seamless.AI Search Queries for Field Service East Sponsors

Use these filters in Seamless.AI to find the right contacts at each target company.

---

## Target Contact Profiles (for each company)

Run 2-3 searches per company targeting these titles:

### Primary Contacts (decision-makers)
- VP Marketing
- Director of Marketing
- Head of Events
- VP Demand Generation
- Director of Field Marketing
- CMO
- VP of Sales
- Director of Partnerships

### Secondary Contacts (budget holders who benefit)
- VP of Sales
- CRO (Chief Revenue Officer)
- VP of Business Development
- Director of Product Marketing

---

## Seamless.AI Filter Settings

### Search 1 — FSM Software (Tier A)
- **Job Title contains:** "VP Marketing" OR "Director Marketing" OR "Head of Events" OR "Field Marketing"
- **Company Name:** [paste from target_companies.txt Tier A list]
- **Seniority:** VP, Director, C-Suite
- **Country:** United States

### Search 2 — IoT / Predictive Maintenance (Tier A/B)
- **Job Title contains:** "VP Marketing" OR "Director Marketing" OR "Events Manager" OR "Demand Generation"
- **Industry:** Software, Technology, Manufacturing Technology
- **Employee Count:** 50-5000
- **Country:** United States

### Search 3 — Training & Knowledge Platforms (Tier B)
- **Job Title contains:** "VP" OR "Director" OR "Head of"
- **Department:** Marketing, Sales
- **Company keywords:** "field service" OR "technician" OR "workforce management"

---

## After You Pull Contacts

1. Export from Seamless.AI as CSV
2. Format the CSV with these columns:
   ```
   company,email,first_name,last_name,title,description
   ```
3. Add company description (copy from target_companies.txt)
4. Run: `python generate_outreach.py --contacts your_contacts.csv`
5. Import hubspot_import.csv into HubSpot Contacts
6. Enroll in a sequence manually or via HubSpot workflow

---

## HubSpot Import Steps

1. Go to **Contacts → Import**
2. Upload `hubspot_import.csv`
3. Map fields:
   - First Name → First Name
   - Last Name → Last Name
   - Job Title → Job Title
   - Company → Company Name
   - Email 1 Subject → Custom property (create: "Outreach Email 1 Subject")
   - Email 1 Body → Custom property (create: "Outreach Email 1 Body")
   - (repeat for Email 2, Email 3)
4. Create a sequence in HubSpot using the email copy
5. Enroll contacts from the imported list
