from flask import Flask, request
import os
from pdf2image import convert_from_path
from loaddatabase import *
from ocr_reader import extract_prescription, extract_disease

app = Flask(__name__)
stored_detected = []


def _conf_badge(conf):
    if conf >= 90:
        cls = "badge-high"
    elif conf >= 75:
        cls = "badge-mid"
    else:
        cls = "badge-low"
    return f'<span class="badge {cls}">{conf}%</span>'


@app.route("/", methods=["GET", "POST"])
def home():
    global stored_detected
    result = ""
    edit_section = ""
    detected_disease = ""
    medicines = get_all_medicines()

    # ── OCR STEP ─────────────────────────────────────────────────────────────
    if request.method == "POST" and "scan" in request.form:
        disease   = request.form.get("disease", "")
        image     = request.files.get("image")
        threshold = 0.50

        if not image or image.filename == "":
            edit_section = '<p class="warn-msg">⚠ Please upload an image.</p>'
        else:
            raw_path = "uploaded_raw"
            image.save(raw_path)

            # Convert PDF to image if needed
            fname = image.filename.lower()
            if fname.endswith(".pdf"):
                pages = convert_from_path(raw_path, dpi=200)
                path = "uploaded.png"
                pages[0].save(path, "PNG")   # use first page
            else:
                path = "uploaded.png"
                os.rename(raw_path, path)

            # Auto-detect disease if not manually provided
            if not disease:
                disease = extract_disease(path)

            detected_disease = disease
            detected_matches = extract_prescription(path, medicines, threshold)
            stored_detected  = [m["name"] for m in detected_matches]

            if detected_matches:
                rows = ""
                for m in detected_matches:
                    auto_dose  = m.get("dose")
                    dose_value = auto_dose if auto_dose else 100
                    tag = (
                        '<span class="dose-tag auto">auto-filled</span>'
                        if auto_dose else
                        '<span class="dose-tag manual">manual</span>'
                    )
                    rows += f"""
                    <tr>
                      <td class="med-name">{m['name'].title()}</td>
                      <td>{_conf_badge(m['confidence'])}</td>
                      <td><code class="token">{m['matched_token']}</code></td>
                      <td class="dose-cell">
                        <input class="dose-input" name="dose_{m['name']}"
                               value="{dose_value}" type="number" min="1" max="5000">
                        <span class="unit">mg</span>
                        {tag}
                      </td>
                    </tr>"""

                edit_section = f"""
                <section class="card results-card">
                  <div class="card-header">
                    <span class="card-icon">💊</span>
                    <div>
                      <h2 class="card-title">Detected Medicines</h2>
                      <p class="card-sub">Review and correct doses before analysis</p>
                    </div>
                  </div>
                  <form method="POST">
                    <input type="hidden" name="disease" value="{disease}">
                    <div class="table-wrap">
                      <table class="med-table">
                        <thead>
                          <tr>
                            <th>Medicine</th>
                            <th>Confidence</th>
                            <th>OCR Token</th>
                            <th>Dose</th>
                          </tr>
                        </thead>
                        <tbody>{rows}</tbody>
                      </table>
                    </div>
                    <div class="card-footer">
                      <button name="analyze" class="btn btn-primary">
                        Run Safety Analysis
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                             stroke="currentColor" stroke-width="2.5"
                             style="margin-left:6px;vertical-align:-2px">
                          <path d="M5 12h14M12 5l7 7-7 7"/>
                        </svg>
                      </button>
                    </div>
                  </form>
                </section>"""
            else:
                edit_section = """
                <div class="warn-box">
                  <strong>No medicines detected.</strong>
                  Try lowering the threshold or use a clearer image.
                </div>"""

    # ── ANALYSIS STEP ────────────────────────────────────────────────────────
    if request.method == "POST" and "analyze" in request.form:
        disease      = request.form.get("disease", "")
        detected_disease = disease
        prescription = {}
        for med in stored_detected:
            try:
                prescription[med] = int(request.form.get(f"dose_{med}", 100))
            except ValueError:
                prescription[med] = 100

        level, score, reasons, adv = analyze_prescription(prescription, disease)

        if score >= 80:
            score_class = "safe"
            score_label = "Safe"
            score_icon  = "✓"
        elif score >= 50:
            score_class = "moderate"
            score_label = "Moderate Risk"
            score_icon  = "⚠"
        else:
            score_class = "high"
            score_label = "High Risk"
            score_icon  = "✕"

        reasons_li = "".join(f"<li>{r}</li>" for r in reasons) if reasons else "<li>No issues found.</li>"
        adv_li     = "".join(f"<li>{a}</li>" for a in adv)     if adv     else "<li>No recommendations.</li>"

        # ── Per-medicine detail cards ──────────────────────────────
        OVERDOSE_EFFECTS = {
            "metformin":      "Lactic acidosis, nausea, vomiting, severe hypoglycemia",
            "glipizide":      "Severe hypoglycemia, seizures, loss of consciousness",
            "insulin":        "Profound hypoglycemia, coma, cardiac arrest",
            "atorvastatin":   "Severe muscle breakdown (rhabdomyolysis), liver damage",
            "simvastatin":    "Rhabdomyolysis, acute kidney injury, liver toxicity",
            "rosuvastatin":   "Muscle pain, liver enzyme elevation, kidney damage",
            "amoxicillin":    "Seizures (at very high doses), severe allergic reaction",
            "ampicillin":     "Neurotoxicity, seizures, electrolyte imbalance",
            "azithromycin":   "Cardiac arrhythmia (QT prolongation), hearing loss",
            "clarithromycin": "QT prolongation, severe GI distress, liver toxicity",
            "lisinopril":     "Severe hypotension, acute kidney failure, hyperkalemia",
            "enalapril":      "Dangerously low blood pressure, kidney impairment",
            "losartan":       "Hypotension, hyperkalemia, acute kidney injury",
            "valsartan":      "Severe hypotension, tachycardia, hyperkalemia",
            "ibuprofen":      "GI bleeding, peptic ulcers, acute kidney injury, heart attack risk",
            "naproxen":       "GI hemorrhage, renal failure, cardiovascular events",
            "warfarin":       "Uncontrolled internal bleeding, hemorrhagic stroke",
            "aspirin":        "GI bleeding, tinnitus, Reye syndrome (children), metabolic acidosis",
            "omeprazole":     "Hypomagnesemia, B12 deficiency, increased fracture risk",
            "pantoprazole":   "Hypomagnesemia, C. difficile infection, bone density loss",
            "sertraline":     "Serotonin syndrome, seizures, severe cardiac effects",
            "fluoxetine":     "Serotonin syndrome, mania, prolonged QT interval",
            "atenolol":       "Severe bradycardia, heart block, bronchospasm",
            "metoprolol":     "Cardiogenic shock, bradycardia, severe hypotension",
            "amlodipine":     "Severe hypotension, reflex tachycardia, peripheral edema",
        }
        WRONG_MED_EFFECTS = {
            "metformin":      "Hypoglycemia in non-diabetics; lactic acidosis risk",
            "glipizide":      "Dangerous blood sugar crash in healthy individuals",
            "insulin":        "Life-threatening hypoglycemia if given to non-diabetics",
            "atorvastatin":   "Muscle damage without cardiovascular benefit",
            "simvastatin":    "Unnecessary muscle/liver stress if cholesterol is normal",
            "rosuvastatin":   "Elevated liver enzymes, muscle pain without benefit",
            "amoxicillin":    "Antibiotic resistance, allergic reactions, gut flora disruption",
            "ampicillin":     "Resistance promotion, rash, diarrhoea without infection benefit",
            "azithromycin":   "Cardiac arrhythmia risk, antibiotic resistance",
            "clarithromycin": "Multiple drug interactions, cardiac risk without infection",
            "lisinopril":     "Dangerous BP drop in normotensive patients, dry cough",
            "enalapril":      "Hypotension, angioedema, kidney stress",
            "losartan":       "Hypotension, dizziness, fetal harm if pregnant",
            "valsartan":      "Hypotension, kidney dysfunction in healthy patients",
            "ibuprofen":      "GI ulcers, kidney damage, masking of serious conditions",
            "naproxen":       "Stomach lining damage, cardiovascular strain",
            "warfarin":       "Catastrophic bleeding risk without clotting disorder",
            "aspirin":        "GI irritation, bleeding risk if no cardiovascular indication",
            "omeprazole":     "Masking of serious GI conditions, nutrient malabsorption",
            "pantoprazole":   "Long-term bone/nutrient issues without acid disorder",
            "sertraline":     "Emotional blunting, serotonin syndrome risk, withdrawal",
            "fluoxetine":     "Agitation, insomnia, serotonin syndrome if misused",
            "atenolol":       "Fatigue, cold extremities, masking hypoglycemia",
            "metoprolol":     "Exercise intolerance, depression, bronchospasm in asthmatics",
            "amlodipine":     "Unnecessary hypotension, ankle swelling, reflex tachycardia",
        }

        med_cards_html = ""
        for med in stored_detected:
            info = medicine_db.get(med, {})
            max_dose   = info.get("MaxDose", 0)
            prescribed = prescription.get(med, 0)
            family     = info.get("Family", "—").title()
            interacts  = info.get("InteractsWith", "none")
            treats     = info.get("Treats", "—").title()
            overdose   = OVERDOSE_EFFECTS.get(med, "Consult a physician immediately.")
            wrong      = WRONG_MED_EFFECTS.get(med, "May cause adverse effects without the correct indication.")

            # Dose bar
            if max_dose and max_dose > 0:
                pct = min(int((prescribed / max_dose) * 100), 100)
                if pct >= 90:   bar_class = "bar-danger"
                elif pct >= 70: bar_class = "bar-warn"
                else:           bar_class = "bar-safe"
                dose_bar = f"""
                  <div class="dose-bar-wrap">
                    <div class="dose-bar-track">
                      <div class="dose-bar-fill {bar_class}" style="width:{pct}%"></div>
                    </div>
                    <span class="dose-bar-label">{prescribed}mg / {max_dose}mg max ({pct}%)</span>
                  </div>"""
            else:
                dose_bar = f'<p class="dose-bar-label">Prescribed: {prescribed}mg &nbsp;·&nbsp; No fixed max dose</p>'

            interacts_html = ", ".join(
                f'<span class="interact-tag">{i.strip().title()}</span>'
                for i in interacts.split(",") if i.strip() != "none"
            ) or '<span class="interact-tag none">None listed</span>'

            med_cards_html += f"""
            <div class="med-detail-card">
              <div class="med-detail-header">
                <div>
                  <span class="med-detail-name">{med.title()}</span>
                  <span class="med-detail-family">{family}</span>
                </div>
                <span class="med-detail-treats">Treats: {treats}</span>
              </div>
              <div class="med-detail-body">
                <div class="med-detail-section">
                  <div class="med-detail-label">Dosage Level</div>
                  {dose_bar}
                </div>
                <div class="med-detail-row2">
                  <div class="med-detail-section">
                    <div class="med-detail-label">⚠ If Overdosed</div>
                    <p class="med-detail-text danger-text">{overdose}</p>
                  </div>
                  <div class="med-detail-section">
                    <div class="med-detail-label">✕ If Wrong Medicine</div>
                    <p class="med-detail-text warn-text">{wrong}</p>
                  </div>
                  <div class="med-detail-section">
                    <div class="med-detail-label">🔗 Interacts With</div>
                    <div class="interact-tags">{interacts_html}</div>
                  </div>
                </div>
              </div>
            </div>"""

        # Alternatives
        alts = suggest_medicines(disease)
        prescribed_names = [m.lower() for m in stored_detected]
        # Filter out already-prescribed medicines
        alts_filtered = [(n, f) for n, f in alts if n.lower() not in prescribed_names]

        if alts_filtered:
            alt_pills = "".join(
                f'<span class="alt-pill"><span class="alt-name">{n}</span>'
                f'<span class="alt-family">{f}</span></span>'
                for n, f in alts_filtered
            )
            alts_html = f'<div class="alt-pills">{alt_pills}</div>'
        else:
            alts_html = '<p class="alt-none">All standard medicines for this condition are already prescribed.</p>'

        result = f"""
        <section class="card analysis-card">
          <div class="card-header">
            <span class="card-icon">📋</span>
            <div>
              <h2 class="card-title">Safety Analysis</h2>
              <p class="card-sub">For: <em>{disease.title()}</em></p>
            </div>
          </div>
          <div class="score-row">
            <div class="score-circle {score_class}">
              <span class="score-num">{score}</span>
              <span class="score-denom">/100</span>
            </div>
            <div class="score-meta">
              <div class="score-label {score_class}">{score_icon} {score_label}</div>
              <p class="score-desc">Based on dosage limits and drug interactions</p>
            </div>
          </div>
          <div class="analysis-grid">
            <div class="analysis-block">
              <h4 class="block-title">Findings</h4>
              <ul class="analysis-list">{reasons_li}</ul>
            </div>
            <div class="analysis-block">
              <h4 class="block-title">Recommendations</h4>
              <ul class="analysis-list">{adv_li}</ul>
            </div>
          </div>
          <div class="alt-section">
            <h4 class="block-title">Alternative Medicines for {disease.title()}</h4>
            {alts_html}
          </div>
        </section>

        <section class="card">
          <div class="card-header">
            <span class="card-icon">💊</span>
            <div>
              <h2 class="card-title">Medicine Details</h2>
              <p class="card-sub">Dosage levels, overdose risks & interaction warnings</p>
            </div>
          </div>
          <div class="med-details-list">
            {med_cards_html}
          </div>
        </section>"""

    # ── PAGE ─────────────────────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Prescription Analyzer</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Serif+Display&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg:       #e8ede8;
      --surface:  #f2f5f2;
      --border:   #c8d4c8;
      --text:     #1e2e1e;
      --muted:    #5a7a5a;
      --teal:     #2a7c6f;
      --teal-lt:  #d4eae5;
      --amber:    #b86e1a;
      --amber-lt: #faebd7;
      --red:      #b83232;
      --red-lt:   #f8e0e0;
      --green:    #1e7a52;
      --green-lt: #d8f0e5;
      --radius:   10px;
      --shadow:   0 1px 3px rgba(0,0,0,0.08), 0 4px 16px rgba(0,0,0,0.08);
    }}

    body {{
      font-family: 'DM Sans', sans-serif;
      background-color: #eef2ee;
      background-image:
        radial-gradient(ellipse 70% 50% at 10% 0%, rgba(42,124,111,0.07) 0%, transparent 60%),
        radial-gradient(ellipse 60% 40% at 90% 100%, rgba(42,124,111,0.05) 0%, transparent 55%);
      color: var(--text);
      min-height: 100vh;
      padding: 0 16px 60px;
    }}

    /* ── Header ── */
    .site-header {{
      max-width: 760px;
      margin: 0 auto;
      padding: 40px 0 28px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 32px;
      display: flex;
      align-items: center;
      gap: 14px;
    }}
    .header-icon {{
      width: 42px; height: 42px;
      background: var(--teal);
      border-radius: 10px;
      display: grid; place-items: center;
      flex-shrink: 0;
      box-shadow: 0 0 0 1px rgba(61,191,168,0.3);
    }}
    .header-icon svg {{ display: block; }}
    .site-title {{
      font-family: 'DM Serif Display', serif;
      font-size: 1.65rem;
      color: #1a2e26;
      letter-spacing: -0.02em;
      line-height: 1;
    }}
    .site-sub {{
      font-size: 0.82rem;
      color: var(--muted);
      margin-top: 3px;
    }}

    /* ── Cards ── */
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      max-width: 760px;
      margin: 0 auto 24px;
      overflow: hidden;
    }}
    .card-header {{
      padding: 20px 24px 16px;
      display: flex;
      align-items: flex-start;
      gap: 14px;
      border-bottom: 1px solid var(--border);
    }}
    .card-icon {{ font-size: 1.4rem; line-height: 1; padding-top: 2px; }}
    .card-title {{
      font-size: 1.05rem;
      font-weight: 600;
      color: var(--text);
    }}
    .card-sub {{ font-size: 0.8rem; color: var(--muted); margin-top: 2px; }}
    .card-footer {{
      padding: 16px 24px;
      border-top: 1px solid var(--border);
      background: rgba(0,0,0,0.03);
    }}

    /* ── Form ── */
    .form-body {{ padding: 20px 24px; display: flex; flex-direction: column; gap: 18px; }}

    .field label {{
      display: block;
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 6px;
    }}
    .field input[type=text],
    .field input[type=number],
    .field input[name=disease] {{
      width: 100%;
      padding: 9px 12px;
      border: 1px solid var(--border);
      border-radius: 7px;
      font-family: inherit;
      font-size: 0.95rem;
      color: var(--text);
      background: var(--bg);
      outline: none;
      transition: border-color 0.15s;
    }}
    .field input:focus {{ border-color: var(--teal); background: #fff; }}

    /* File input */
    .file-zone {{
      border: 1.5px dashed var(--border);
      border-radius: 7px;
      background: var(--bg);
      transition: border-color 0.15s;
      overflow: hidden;
    }}
    .file-zone:focus-within {{ border-color: var(--teal); }}
    .file-add-btn {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      cursor: pointer;
      font-size: 0.88rem;
      color: var(--muted);
      transition: color 0.15s;
      border: none; background: none;
      font-family: inherit;
      width: 100%;
    }}
    .file-add-btn:hover {{ color: var(--teal); }}
    .file-add-btn input {{ display: none; }}
    .file-add-btn .file-icon {{ font-size: 1.05rem; flex-shrink:0; }}
    .file-list {{
      list-style: none;
      border-top: 1px solid var(--border);
    }}
    .file-list:empty {{ display: none; }}
    .file-item {{
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 14px;
      font-size: 0.85rem;
      color: var(--text);
      border-bottom: 1px solid #f0eeea;
      animation: fadeIn 0.18s ease;
    }}
    .file-item:last-child {{ border-bottom: none; }}
    .file-item-name {{
      flex: 1;
      min-width: 0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .file-item-size {{ font-size: 0.75rem; color: var(--muted); flex-shrink:0; }}
    .file-remove {{
      background: none; border: none; cursor: pointer;
      color: var(--muted); font-size: 1rem; padding: 0 2px;
      line-height: 1; flex-shrink:0;
      transition: color 0.12s;
    }}
    .file-remove:hover {{ color: var(--red); }}
    @keyframes fadeIn {{ from {{ opacity:0; transform:translateY(-4px); }} to {{ opacity:1; transform:none; }} }}

    /* ── Buttons ── */
    .btn {{
      display: inline-flex;
      align-items: center;
      padding: 9px 20px;
      border: none;
      border-radius: 7px;
      font-family: inherit;
      font-size: 0.9rem;
      font-weight: 500;
      cursor: pointer;
      transition: opacity 0.15s, transform 0.1s;
    }}
    .btn:active {{ transform: scale(0.98); }}
    .btn-teal  {{ background: var(--teal);  color: #fff; }}
    .btn-teal:hover  {{ opacity: 0.88; }}
    .btn-primary {{ background: var(--text); color: #fff; }}
    .btn-primary:hover {{ opacity: 0.85; }}

    /* ── Results table ── */
    .table-wrap {{ padding: 4px 24px 0; overflow-x: auto; }}
    .med-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
    }}
    .med-table th {{
      text-align: left;
      padding: 10px 10px 8px;
      font-size: 0.74rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      border-bottom: 1px solid var(--border);
    }}
    .med-table td {{
      padding: 11px 10px;
      border-bottom: 1px solid #f0eeea;
      vertical-align: middle;
    }}
    .med-table tr:last-child td {{ border-bottom: none; }}
    .med-table tr:hover td {{ background: rgba(0,0,0,0.03); }}

    .med-name {{ font-weight: 500; font-size: 0.93rem; }}
    .token {{
      font-size: 0.78rem;
      font-family: 'Courier New', monospace;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 2px 6px;
      color: var(--muted);
    }}

    .dose-cell {{ display: flex; align-items: center; gap: 6px; }}
    .dose-input {{
      width: 68px;
      padding: 5px 8px;
      border: 1px solid var(--border);
      border-radius: 6px;
      font-family: inherit;
      font-size: 0.88rem;
      text-align: right;
      outline: none;
      transition: border-color 0.15s;
    }}
    .dose-input:focus {{ border-color: var(--teal); }}
    .unit {{ font-size: 0.78rem; color: var(--muted); }}

    /* Badges */
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 20px;
      font-size: 0.75rem;
      font-weight: 600;
    }}
    .badge-high {{ background: var(--green-lt); color: var(--green); }}
    .badge-mid  {{ background: var(--amber-lt); color: var(--amber); }}
    .badge-low  {{ background: var(--red-lt);   color: var(--red);   }}

    .dose-tag {{
      font-size: 0.7rem;
      padding: 1px 6px;
      border-radius: 4px;
      font-weight: 500;
    }}
    .dose-tag.auto   {{ background: var(--teal-lt);  color: var(--teal);  }}
    .dose-tag.manual {{ background: var(--bg); color: var(--muted); border: 1px solid var(--border); }}

    /* ── Analysis result ── */
    .score-row {{
      display: flex;
      align-items: center;
      gap: 20px;
      padding: 24px;
      border-bottom: 1px solid var(--border);
    }}
    .score-circle {{
      width: 90px; height: 90px;
      border-radius: 50%;
      border: 3px solid;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }}
    .score-circle.safe     {{ border-color: var(--green); color: var(--green); }}
    .score-circle.moderate {{ border-color: var(--amber); color: var(--amber); }}
    .score-circle.high     {{ border-color: var(--red);   color: var(--red);   }}
    .score-num  {{ font-size: 1.55rem; font-weight: 700; line-height: 1; }}
    .score-denom {{ font-size: 0.68rem; color: var(--muted); margin-top: 2px; }}

    .score-label {{
      font-size: 1.1rem;
      font-weight: 600;
      margin-bottom: 4px;
    }}
    .score-label.safe     {{ color: var(--green); }}
    .score-label.moderate {{ color: var(--amber); }}
    .score-label.high     {{ color: var(--red);   }}
    .score-desc {{ font-size: 0.8rem; color: var(--muted); }}

    .analysis-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0;
    }}
    .analysis-block {{ padding: 20px 24px; }}
    .analysis-block:first-child {{ border-right: 1px solid var(--border); }}
    .block-title {{
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: var(--muted);
      margin-bottom: 10px;
    }}
    .analysis-list {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 7px;
    }}
    .analysis-list li {{
      font-size: 0.86rem;
      padding-left: 14px;
      position: relative;
      line-height: 1.45;
      color: var(--text);
    }}
    .analysis-list li::before {{
      content: '—';
      position: absolute;
      left: 0;
      color: var(--muted);
    }}

    /* ── Warn ── */
    .warn-box {{
      max-width: 760px;
      margin: 0 auto 24px;
      background: var(--amber-lt);
      border: 1px solid #f0d9b0;
      border-radius: var(--radius);
      padding: 14px 18px;
      font-size: 0.88rem;
      color: #7a4e10;
    }}
    .warn-msg {{
      max-width: 760px;
      margin: 0 auto 16px;
      color: var(--red);
      font-size: 0.88rem;
    }}

    /* ── Alternatives ── */
    .alt-section {{
      padding: 18px 24px 20px;
      border-top: 1px solid var(--border);
    }}
    .alt-section .block-title {{ margin-bottom: 12px; }}
    .alt-pills {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .alt-pill {{
      display: flex;
      flex-direction: column;
      background: var(--teal-lt);
      border: 1px solid rgba(61,191,168,0.25);
      border-radius: 8px;
      padding: 7px 12px;
      transition: border-color 0.15s, transform 0.1s;
      cursor: default;
    }}
    .alt-pill:hover {{
      border-color: var(--teal);
      transform: translateY(-1px);
    }}
    .alt-name {{
      font-size: 0.88rem;
      font-weight: 600;
      color: var(--teal);
    }}
    .alt-family {{
      font-size: 0.72rem;
      color: var(--muted);
      margin-top: 1px;
      text-transform: capitalize;
    }}
    .alt-none {{
      font-size: 0.84rem;
      color: var(--muted);
      font-style: italic;
    }}

    /* ── Medicine Detail Cards ── */
    .med-details-list {{
      padding: 16px 24px 20px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }}
    .med-detail-card {{
      border: 1px solid var(--border);
      border-radius: 9px;
      overflow: hidden;
    }}
    .med-detail-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 16px;
      background: rgba(42,124,111,0.05);
      border-bottom: 1px solid var(--border);
      flex-wrap: wrap;
      gap: 6px;
    }}
    .med-detail-name {{
      font-weight: 700;
      font-size: 0.97rem;
      color: var(--text);
      margin-right: 8px;
    }}
    .med-detail-family {{
      font-size: 0.72rem;
      background: var(--teal-lt);
      color: var(--teal);
      border: 1px solid rgba(61,191,168,0.25);
      border-radius: 4px;
      padding: 1px 7px;
      font-weight: 500;
    }}
    .med-detail-treats {{
      font-size: 0.75rem;
      color: var(--muted);
    }}
    .med-detail-body {{
      padding: 12px 16px 14px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .med-detail-label {{
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      margin-bottom: 5px;
    }}
    .med-detail-row2 {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 12px;
    }}
    .med-detail-text {{
      font-size: 0.82rem;
      line-height: 1.5;
      margin: 0;
    }}
    .danger-text {{ color: var(--red); }}
    .warn-text   {{ color: var(--amber); }}

    /* Dose bar */
    .dose-bar-wrap {{ display: flex; align-items: center; gap: 10px; }}
    .dose-bar-track {{
      flex: 1;
      height: 7px;
      background: var(--border);
      border-radius: 99px;
      overflow: hidden;
    }}
    .dose-bar-fill {{
      height: 100%;
      border-radius: 99px;
      transition: width 0.4s ease;
    }}
    .bar-safe   {{ background: var(--green); }}
    .bar-warn   {{ background: var(--amber); }}
    .bar-danger {{ background: var(--red);   }}
    .dose-bar-label {{
      font-size: 0.75rem;
      color: var(--muted);
      white-space: nowrap;
    }}

    /* Interact tags */
    .interact-tags {{ display: flex; flex-wrap: wrap; gap: 5px; margin-top: 2px; }}
    .interact-tag {{
      font-size: 0.72rem;
      background: var(--amber-lt);
      color: var(--amber);
      border: 1px solid rgba(232,162,58,0.25);
      border-radius: 4px;
      padding: 2px 7px;
    }}
    .interact-tag.none {{ background: var(--bg); color: var(--muted); border-color: var(--border); }}

    @media (max-width: 560px) {{
      .analysis-grid {{ grid-template-columns: 1fr; }}
      .analysis-block:first-child {{ border-right: none; border-bottom: 1px solid var(--border); }}
      .score-row {{ flex-direction: column; align-items: flex-start; }}
    }}
  </style>
</head>
<body>

  <header class="site-header">
    <div class="header-icon">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
           stroke="#ffffff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4.8 2.3A.3.3 0 1 0 5 2H4a2 2 0 0 0-2 2v5a6 6 0 0 0 6 6 6 6 0 0 0 6-6V4a2 2 0 0 0-2-2h-1a.3.3 0 1 0 .2.3"/>
        <path d="M8 15v1a6 6 0 0 0 6 6v0a6 6 0 0 0 6-6v-4"/>
        <circle cx="20" cy="10" r="2"/>
      </svg>
    </div>
    <div>
      <div class="site-title">Prescription Analyzer</div>
      <div class="site-sub">OCR-powered medicine detection & safety check</div>
    </div>
  </header>

  <!-- Upload form -->
  <section class="card">
    <div class="card-header">
      <span class="card-icon">📄</span>
      <div>
        <h2 class="card-title">Scan Prescription</h2>
        <p class="card-sub">Upload an image or PDF to extract medicines automatically</p>
      </div>
    </div>

    <form method="POST" enctype="multipart/form-data">
      <div class="form-body">

        <div class="field">
          <label for="disease">
            Diagnosis / Disease
            <span id="auto-tag" style="display:none;margin-left:6px;
              font-size:0.72rem;font-weight:500;color:var(--teal);
              background:var(--teal-lt);padding:1px 7px;border-radius:4px;
              text-transform:none;letter-spacing:0">
              auto-detected
            </span>
          </label>
          <input id="disease" type="text" name="disease"
                 placeholder="e.g. hypertension, diabetes"
                 value="{detected_disease}" required>
        </div>

        <div class="field">
          <label>Prescription Image</label>
          <div class="file-zone" id="file-zone">
            <label class="file-add-btn">
              <span class="file-icon">📎</span>
              <span id="file-prompt">Choose an image or PDF</span>
              <input type="file" name="image" accept="image/*,.pdf,application/pdf" id="file-input">
            </label>
            <ul class="file-list" id="file-list"></ul>
          </div>
          <script>
          (function() {{
            const input   = document.getElementById('file-input');
            const list    = document.getElementById('file-list');
            const prompt  = document.getElementById('file-prompt');
            let files     = [];

            function fmtSize(b) {{
              return b < 1024 ? b + ' B'
                : b < 1048576 ? (b/1024).toFixed(1) + ' KB'
                : (b/1048576).toFixed(1) + ' MB';
            }}

            function renderList() {{
              list.innerHTML = '';
              files.forEach((f, i) => {{
                const li = document.createElement('li');
                li.className = 'file-item';
                li.innerHTML = `
                  <span class="file-item-name" title="${{f.name}}">${{f.name}}</span>
                  <span class="file-item-size">${{fmtSize(f.size)}}</span>
                  <button type="button" class="file-remove" data-i="${{i}}" title="Remove">✕</button>`;
                list.appendChild(li);
              }});
              // Rebuild hidden inputs so form submits the right file
              document.querySelectorAll('input.dyn-file').forEach(e => e.remove());
              if (files.length > 0) {{
                // Use a DataTransfer to set files on the visible input
                const dt = new DataTransfer();
                files.forEach(f => dt.items.add(f));
                input.files = dt.files;
              }}
              prompt.textContent = files.length ? 'Add another file' : 'Choose an image or PDF';
            }}

            input.addEventListener('change', function() {{
              Array.from(this.files).forEach(f => {{
                if (!files.find(x => x.name === f.name && x.size === f.size))
                  files.push(f);
              }});
              this.value = '';
              renderList();
            }});

            list.addEventListener('click', function(e) {{
              const btn = e.target.closest('.file-remove');
              if (!btn) return;
              files.splice(+btn.dataset.i, 1);
              renderList();
            }});
          }})();
          </script>
        </div>
</div>
      <div class="card-footer">
        <button name="scan" class="btn btn-teal">
          Scan Prescription
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2.5"
               style="margin-left:6px;vertical-align:-2px">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
          </svg>
        </button>
      </div>
    </form>
  </section>

  {edit_section}
  {result}

  <script>
    (function() {{
      const d = document.getElementById('disease');
      const tag = document.getElementById('auto-tag');
      if (d && d.value.trim()) {{
        tag.style.display = 'inline';
      }}
      d.addEventListener('input', function() {{
        tag.style.display = 'none';
      }});
    }})();
  </script>
</body>
</html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)