#!/usr/bin/env python3
"""One-time setup: add the "Blurb" property to the wiki and fill in starter blurbs.

    python3 scripts/seed_blurbs.py

Blurbs are short public definitions shown on the website. This only writes a blurb where the
page's Blurb is still empty, so it never overwrites one you've edited. Safe to run again.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_notion as notion  # noqa: E402

# Starter blurbs keyed by skill name (general definitions; edit them freely in Notion or the admin).
BLURBS = {
    "Mechanical": "Designing, analyzing and building physical things: parts, mechanisms and machines.",
    "Electrical": "Circuits, power, sensors and embedded hardware that make machines sense and move.",
    "Software": "Code that runs robots and tools, from embedded firmware to web apps and ROS.",
    "Systems": "Holding the whole project together: requirements, architecture, integration and planning.",
    "Other": "Creative and supporting skills that round out the engineering work.",
    "3D Printing / Plastics": "Designing for and producing parts with FDM/resin printers and common plastics.",
    "Agile & Execution": "Planning work in short iterations, tracking progress and shipping on schedule.",
    "Ansible": "Automation tool for configuring machines and deploying software over SSH with repeatable playbooks.",
    "Autodesk": "Autodesk's design tools (Fusion 360, Inventor, AutoCAD) for modeling and drafting.",
    "Automation / PLCs": "Industrial control with programmable logic controllers running machines and production lines.",
    "Behavior Planning": "Deciding what a robot should do next: task logic, state machines and behavior trees.",
    "BOM & Cost Management": "Tracking every part in a build, its source and cost, and keeping the budget in check.",
    "C++": "Fast, low-level language used for robotics, embedded systems and performance-critical code.",
    "Cabinet Design": "Laying out electrical enclosures: power distribution, controllers, terminals and wiring.",
    "CAD": "Computer-aided design: modeling parts and assemblies in 3D and turning them into drawings.",
    "CAN Communication": "Robust two-wire bus used in vehicles and robots for devices to share messages.",
    "Capcut": "Video editing app for cutting, captioning and polishing short-form content.",
    "Circuit Components / Prototyping": "Choosing resistors, ICs and connectors, and building circuits on breadboards and protoboards.",
    "CMake": "Build system generator that configures and compiles C/C++ projects across platforms.",
    "Communication Protocols": "The rules devices use to talk: buses, serial links and network protocols.",
    "Connectors, Cabling, and Fabrication": "Making reliable harnesses: crimping, connector selection, routing and strain relief.",
    "Control Theory": "Math for making systems follow commands: feedback loops, PID, stability and tuning.",
    "Creative Tech": "Using engineering tools for art, fashion, video and interactive experiences.",
    "CREO": "PTC Creo, a parametric CAD package for detailed part and assembly design.",
    "Data Analysis": "Cleaning, plotting and interpreting data to find what's actually going on.",
    "Dev Environment": "Setting up editors, toolchains and OS environments so development runs smoothly.",
    "DevOps & Build": "Version control, builds, containers and deployment that keep software reproducible.",
    "Diagramming & Design Tools": "Tools for drawing architecture, wiring and flow diagrams that explain a design.",
    "Docker": "Packages software and its dependencies into containers that run the same anywhere.",
    "DrawIO": "Free diagramming tool (diagrams.net) for flowcharts, block diagrams and architectures.",
    "Dynamics": "How forces and torques make bodies move: accelerations, inertia and loads.",
    "Engineering Drawings": "2D drawings that communicate geometry, dimensions and tolerances for manufacturing.",
    "EtherCAT": "Real-time industrial Ethernet protocol for fast, synchronized motion control.",
    "Fashion + Robotics": "Wearables and garments that blend clothing design with electronics and motion.",
    "FEA": "Finite element analysis: simulating stress, deflection and heat in parts before building them.",
    "Flask": "Lightweight Python web framework for building small web apps and APIs.",
    "Foxglove Studios": "Visualization tool for ROS data: plots, 3D views and log playback.",
    "GD&T": "Geometric dimensioning and tolerancing: precise language for how much a part may vary.",
    "Git": "Version control for tracking changes, branching and collaborating on code.",
    "Hardware Drivers": "Low-level code that lets software talk to motors, sensors and other devices.",
    "Industrial Wiring Diagrams": "Schematics and ladder-style drawings that document how industrial panels are wired.",
    "Integration & Bring-up": "Getting new hardware and software working together for the first time.",
    "Kinematics": "The geometry of motion: positions, velocities and how joints move an arm or mechanism.",
    "Lab Tools": "Multimeters, oscilloscopes, power supplies and analyzers for testing electronics.",
    "Linux": "The open-source OS behind most robots and servers: shell, services and system setup.",
    "Machine Design": "Designing mechanical systems from components like shafts, bearings, gears and fasteners.",
    "Machine Learning": "Training models from data to recognize patterns and make predictions.",
    "Manufacturing (DFM)": "Design for manufacturing: shaping parts so they're easy and cheap to make.",
    "Materials": "Choosing metals, plastics and composites by strength, weight, cost and process.",
    "Mechanisms": "Linkages, cams, gears and other arrangements that turn one motion into another.",
    "Microcontrollers / Embedded Systems": "Small computers inside devices that read sensors and drive hardware in real time.",
    "Motors": "Selecting and driving DC, stepper, BLDC and servo motors for motion.",
    "Multiprocessing / Multithreading": "Running work in parallel across threads and processes without stepping on each other.",
    "Networking": "How devices connect and talk: IP, Wi-Fi, ports and troubleshooting connections.",
    "Onshape": "Cloud-based CAD for modeling and collaborating on parts and assemblies in the browser.",
    "OpenCV": "Open-source computer vision library for image processing and camera-based detection.",
    "Path / Motion Planning": "Finding collision-free paths and smooth trajectories for robots to follow.",
    "PCB Design": "Laying out printed circuit boards: schematics, footprints, routing and fabrication files.",
    "Perception / Computer Vision": "Helping robots understand the world from cameras and sensors.",
    "PlatformIO": "Toolchain and IDE plugin for building and flashing embedded firmware across many boards.",
    "Power": "Supplying and distributing power safely: batteries, regulators, fusing and budgets.",
    "Programming Languages": "The languages I write software in, from Python scripting to C++.",
    "Project Management": "Scoping, scheduling and coordinating work so a project actually ships.",
    "Python": "Versatile language for scripting, automation, data work, web backends and robotics.",
    "Raspberry PI": "Small single-board Linux computer used for prototypes, robots and camera projects.",
    "Requirements": "Writing down what a system must do, clearly enough to design and test against.",
    "Risk & Reliability": "Spotting what could fail, how likely it is, and designing to prevent it.",
    "Robot Control": "Software that turns commands into joint and motor actions on a real robot.",
    "Robotic Arms": "Multi-joint manipulators: design, kinematics and control of arms that reach and grasp.",
    "ROS1": "The original Robot Operating System: nodes, topics and tools for robot software.",
    "ROS2": "Modern Robot Operating System with real-time-friendly middleware for robot software.",
    "Rotations": "Representing 3D orientation with rotation matrices, Euler angles and quaternions.",
    "RTOS (Linux)": "Making Linux behave predictably in real time for control loops and timing-critical code.",
    "RTOS (Microcontroller)": "Real-time operating systems like FreeRTOS that schedule tasks on microcontrollers.",
    "Safety & Standards": "Designing to safety rules and industry standards so machines protect people.",
    "Screws": "Choosing threaded fasteners: sizes, threads, torque and joint design.",
    "Sensors": "Measuring the world: encoders, IMUs, distance, force and other sensor types.",
    "Serial Protocols": "UART, I2C and SPI: simple wired links between chips and boards.",
    "Shop & Prototyping": "Hands-on fabrication with shop tools to build and iterate on physical prototypes.",
    "Simulation": "Testing robots and designs in virtual environments before building them.",
    "Software Architecture": "Structuring code into clear components and interfaces that scale and stay maintainable.",
    "Solidworks": "Industry-standard parametric CAD for parts, assemblies and drawings.",
    "State Estimation / Localization": "Working out where a robot is and how it's moving from noisy sensor data.",
    "State Machine Diagrams": "Drawing system behavior as states and transitions to design clear control logic.",
    "Support and Connection Types": "How joints and supports constrain parts, and the reaction forces they create.",
    "System Architecture & Interfaces": "Breaking a system into subsystems and defining how they connect.",
    "Systems Engineering": "Engineering the whole system: requirements, architecture, integration and verification.",
    "Technical Communication": "Explaining technical work clearly through docs, diagrams and presentations.",
    "Thermal": "Heat transfer and cooling: keeping motors, electronics and parts within temperature limits.",
    "Touch Designer": "Node-based visual programming tool for real-time graphics and interactive installations.",
    "TwinCAT": "Beckhoff's PC-based automation software for PLC programming and motion control.",
    "USB": "The universal serial bus: connecting, powering and communicating with devices.",
    "Vendor & Supplier Management": "Finding suppliers, getting quotes and keeping parts arriving on time.",
    "Verification & Validation": "Proving a system was built right and that it's the right system.",
    "WebDev": "Building websites and web apps: HTML, CSS, JavaScript and backends.",
    "Windows": "Setting up and developing on Windows, including tooling and WSL.",
}


def main():
    try:
        ds = notion.request("GET", f"/data_sources/{notion.DATA_SOURCE_ID}")
        if "Blurb" not in ds["properties"]:
            notion.request("PATCH", f"/data_sources/{notion.DATA_SOURCE_ID}", {"properties": {"Blurb": {"rich_text": {}}}})
            print('Added the "Blurb" property to the Engineering Wiki.')
        records = notion.fetch_records()
    except notion.NotionError as e:
        sys.exit(str(e))

    written = skipped = 0
    for r in records:
        text = BLURBS.get(r["name"])
        if not text or not notion.is_skill(r):
            continue
        if r["blurb"]:
            skipped += 1  # already has one: leave it alone
            continue
        notion.request("PATCH", f"/pages/{r['id']}", {"properties": {"Blurb": {"rich_text": [{"text": {"content": text}}]}}})
        written += 1
        print(f"  {r['name']}")
    print(f"Wrote {written} blurbs, left {skipped} existing ones alone.")


if __name__ == "__main__":
    main()
