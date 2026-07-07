"""Applies the CSV export fix to app.py — replaces the old file-write approach with Desktop save."""
import re, pathlib

app = pathlib.Path("app.py").read_text(encoding="utf-8")

old = '''        if st.button("📥 Export Pipeline to CSV"):
            rows = []
            for c in pipeline:
                rows.append({
                    "Company": c.get("company",""),
                    "Score": c.get("score",""),
                    "Tier": c.get("tier",""),
                    "Status": c.get("status",""),
                    "Contact Name": c.get("contact_name",""),
                    "Contact Title": c.get("contact_title",""),
                    "Contact Email": c.get("contact_email",""),
                    "What They Do": c.get("what_they_do",""),
                    "Pitch Angle": c.get("pitch_angle",""),
                })
            with open("pipeline_export.csv", "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            st.success("Saved to pipeline_export.csv")'''

new = '''        if st.button("📥 Export Pipeline to CSV"):
            rows = []
            for c in pipeline:
                rows.append({
                    "Company": c.get("company",""),
                    "Score": c.get("score",""),
                    "Tier": c.get("tier",""),
                    "Status": c.get("status",""),
                    "Contact Name": c.get("contact_name",""),
                    "Contact Title": c.get("contact_title",""),
                    "Contact Email": c.get("contact_email",""),
                    "What They Do": c.get("what_they_do",""),
                    "Pitch Angle": c.get("pitch_angle",""),
                })
            import pathlib as _pl
            desktop = _pl.Path.home() / "Desktop" / "pipeline_export.csv"
            with open(desktop, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            st.success(f"✅ Saved to Desktop: pipeline_export.csv")'''

if old in app:
    app = app.replace(old, new)
    pathlib.Path("app.py").write_text(app, encoding="utf-8")
    print("✅ Fix applied successfully.")
else:
    print("⚠️  Could not find the old export block — app.py may have already been updated or changed.")
