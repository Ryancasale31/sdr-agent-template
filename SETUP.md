# Setup Guide — Field Service East SDR Agent

## 1. Install Python
Download from: https://www.python.org/downloads/
- Check "Add Python to PATH" during install
- Use Python 3.11 or newer

## 2. Get your Anthropic API Key
- Go to: https://console.anthropic.com/keys
- Create a new key
- Copy it

## 3. Set up the project
Open PowerShell and run:
```powershell
cd C:\Users\Ryan.Casale\Downloads\fse_sdr_agent
pip install anthropic pandas python-dotenv rich
copy .env.example .env
```
Then open `.env` and replace `your_key_here` with your actual API key.

## 4. Run the agent (in order)

### Step 1 — Analyze your attendee list
```powershell
python icp_profile.py
```
Outputs: `icp_summary.json`

### Step 2 — Score all target companies
```powershell
python score_company.py --batch target_companies.txt
```
Outputs: `scored_companies.json` (sorted by fit score)
Takes about 2-3 minutes. Uses ~$0.10 of API credits.

### Step 3 — Pull contacts from Seamless.AI
See `seamless_search_queries.md` for exact search filters.
Export your contacts as CSV with these columns:
```
company,email,first_name,last_name,title,description
```

### Step 4 — Generate email sequences
```powershell
python generate_outreach.py --contacts your_contacts.csv
```
Outputs: `sequences.json` and `hubspot_import.csv`

### Step 5 — Import to HubSpot
See `seamless_search_queries.md` → HubSpot Import Steps.

---

## Quick single-company test
```powershell
python score_company.py "ServiceMax" "Field service management software for asset-intensive industries"
```

## Generate one sequence manually
```powershell
python generate_outreach.py "ServiceMax" "jsmith@servicemax.com" "John Smith" "VP Marketing" --description "FSM software for medical and industrial"
```
