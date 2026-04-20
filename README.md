
<p align="center">
  <img src="LoGo.png" width="250" alt="NetSense AI Logo">
</p>
<h1>🚀 NetSense AI – Day 4 Update</h1>

### 🤖 AI Recommendation Engine + Chatbot + Controlled UI Trigger

---

## 📌 Overview

Day 4 focuses on transforming NetSense AI from a simple monitoring tool into an **intelligent network assistant**.

This update introduces:

* 🧠 Rule-based AI recommendations
* 💬 Basic chatbot for user interaction
* 🎯 Controlled UI behavior (manual snapshot-based updates)

---

## 🧠 AI Recommendation Engine

The system now analyzes network metrics and provides intelligent suggestions.

### ⚙️ How it Works

* Uses rule-based logic (if-else conditions)
* Evaluates:

  * 📡 Ping
  * ⚡ Download Speed
  * 📤 Upload Speed
* Generates:

  * Network status (Good / Poor / Unstable)
  * Issue summary
  * Actionable recommendations

### 🧾 Example

```json
{
  "status": "Unstable",
  "recommendations": [
    "High ping detected. Check network stability.",
    "Reduce background internet usage."
  ]
}
```

---

## 💬 Basic Chatbot

A simple chatbot is introduced to interact with users using real-time network data.

### ✅ Supported Queries

* "How is my network?"
* "Why is my ping high?"
* "How can I improve speed?"
* "What is my download speed?"

### ⚙️ How it Works

* Accepts user input
* Uses rule-based logic + current metrics
* Returns human-readable responses

---

## 🎯 Controlled UI Behavior (Major Fix)

### ❗ Problem

Previously, network values were:

* Automatically displayed on page load ❌
* Continuously updating ❌

### ✅ Solution

Now the UI behaves as a **manual snapshot viewer**:

### 🔄 New Flow

1. Page Load:

   * Shows placeholders: `--`
   * Displays message:
     👉 *"Press Test Performance to view results"*

2. On Button Click:

   * Shows loading animation (`...`)
   * Fetches latest stored backend data
   * Displays values with animation

3. After Display:

   * UI stays idle ✅
   * No auto-refresh ❌

4. On Next Click:

   * Fetches latest data again
   * Updates with animation

---

## 🎨 UI Improvements

* ✨ Smooth value update animations
* 📊 Clean status display
* 🤖 AI recommendation section added
* 💬 Chatbot interface integrated

---

## 🛠️ Tech Stack

### Backend

* Python
* Flask

### Frontend

* HTML
* CSS (Glassmorphism UI)
* JavaScript (Fetch API + animations)

---

## 🚀 Key Highlights

* 🧠 Introduced AI-like intelligence using rule-based logic
* 💬 Built an interactive chatbot system
* 🎯 Fixed UI auto-refresh issue (major UX improvement)
* ⚡ Implemented manual trigger-based performance display

---

## 🧩 What’s Next (Day 5 Preview)

* 🔗 Chatbot connected to live metrics dynamically
* ⚙️ Start automation (e.g., DNS fix)
* 🛠️ “Fix Issue” button integration


