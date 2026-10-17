# Partial Submission

**Team Name:** EcoTech

**Team Members:**
- Rodrigo Eidji Kurogi
- João Pedro Peressin Beduschi
- Fabio Makoto

## 1. Problem

Industrial waste collection often relies on fixed routes and schedules, resulting in unnecessary trips, underutilized trucks, and wasted fuel. This increases operating costs and CO₂ emissions. The problem is particularly relevant to industries that generate large volumes of waste and need to make their logistics more efficient and sustainable.

## 2. Target Audience

Industries that generate large volumes of waste, especially in the food processing, metalworking, and manufacturing sectors. The solution primarily serves logistics, sustainability, and operations managers, as well as third-party companies responsible for collecting and transporting industrial waste.

## 3. Proposed Solution

Develop an intelligent reverse logistics platform that monitors the fill levels of industrial waste containers and automatically optimizes collection routes. The goal is to reduce unnecessary travel, fuel costs, and CO₂ emissions, delivering financial savings and greater operational efficiency.

## 4. How It Works

IoT sensors installed in the containers monitor waste volume and send the data to an online platform. An algorithm analyzes fill levels, predicts when collection is needed, and determines optimized routes based on distance, truck capacity, and urgency. A dashboard displays indicators related to costs, savings, and environmental impact.

### System Architecture

```text
Ultrasonic Sensor → ESP32 → Wi-Fi → Monitoring Platform → Route Optimization
```

1. **Ultrasonic sensor:** Measures the distance from the top of a waste container to the waste surface to estimate its fill level.
2. **ESP32:** Reads the sensor data and calculates an estimated fill percentage.
3. **Wi-Fi:** Uses the ESP32's built-in wireless connectivity to transmit measurements.
4. **Monitoring platform:** Receives and displays container fill levels for remote monitoring.
5. **Route optimization:** Uses the fill-level data to prioritize containers for collection and plan more efficient truck routes.

**Measurement note:** The ultrasonic sensor measures distance, not waste volume directly. Irregular waste surfaces may affect fill-level estimates, so the prototype will require calibration and testing.

## 5. Competitive Advantage

Unlike traditional collection systems that use fixed routes, the solution uses real-time data to schedule collections based on actual needs. The platform integrates IoT, route optimization, and environmental and financial indicators, making it possible to track cost savings, emissions reductions, and return on investment (ROI).

## 6. Evidence and Initial Validation

The initial validation is conceptual, based on the identification of inefficiencies in collection systems that use fixed schedules and routes. As the next validation step, simulations will be conducted to compare traditional and intelligent routes using realistic synthetic data.

## 7. Next Steps

Develop a minimum viable product (MVP) with level sensors connected to an ESP32 microcontroller, a database, and a monitoring platform. Implement a routing algorithm and a dashboard with financial and environmental indicators. Conduct simulated tests, validate the prototype at a partner industrial facility, and assess implementation costs, potential savings, and scalability.

---

**Project Overview:** CicloRota – Dynamic Reverse Logistics Management  
**Event:** SancaThon 2026
