# Safescript

> A Python-based OCR system that extracts, processes, and structures medical data from documents using image processing and database integration.

---

## ✨ Overview

**CodePulse** is designed to automate the extraction of information from medical documents using **OCR (Optical Character Recognition)** and convert unstructured data into structured, usable formats.

This project demonstrates:

* Real-world data processing
* OCR pipeline implementation
* Backend system design
* Integration of multiple technologies

---

## 🔥 Key Features

* 📄 **OCR Extraction** — Reads text from images and documents
* 🧠 **Data Processing** — Identifies prescriptions and diseases
* 🗄️ **Database Integration** — Loads and queries structured data
* ⚙️ **Automated Pipeline** — Input → Processing → Output
* 🌐 **Flask Backend** — Runs as a simple web application

---

## 🛠️ Tech Stack

* **Language:** Python
* **Backend:** Flask
* **OCR:** Tesseract (via `pytesseract`)
* **Image Processing:** OpenCV (`cv2`)
* **Data Handling:** Pandas
* **PDF Processing:** pdf2image

---

## 📁 Project Structure

```bash id="8q1t4f"
CodePulse/
│── app.py                # Main Flask app (entry point)
│── ocr_reader.py         # OCR + extraction logic
│── loaddatabase.py       # Data loading
│── createdatabase.py     # Database creation
│── medical_database.xlsx # Dataset
│── requirements.txt      # Dependencies
```

---

## ⚙️ Setup & Installation

### 1️⃣ Clone the repository

```bash id="p3p5c9"
git clone https://github.com/Anik03-cmd/CodePulse.git
cd CodePulse
```

### 2️⃣ Install dependencies

```bash id="6ahvcm"
pip install -r requirements.txt
```

### 3️⃣ Install system dependencies (Linux / Codespaces)

```bash id="9rsxqz"
sudo apt-get update
sudo apt-get install -y tesseract-ocr poppler-utils libgl1
```

---

## ▶️ Run the Application

```bash id="q9rt3k"
python app.py
```

Then open:

```
http://127.0.0.1:5000
```

---

## 🔄 Workflow

1. Upload a document/image
2. OCR extracts text
3. Data is analyzed (prescription & disease detection)
4. Information is processed and matched with database
5. Output is generated

---

## 🚀 Future Improvements

* 🌐 Full frontend interface (React / improved UI)
* 🤖 AI-based medical recommendations
* 📊 Visualization dashboard
* ☁️ Deployment (cloud hosting)

---

## 💡 Why This Project Matters

This project highlights:

* Handling **unstructured → structured data**
* Integration of **OCR + backend systems**
* Practical problem-solving with real-world data

---

## 👨‍💻 Author

**Anik Biswas**
🔗 https://github.com/Anik03-cmd
