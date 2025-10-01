# Product Overview: Crowdsourced Video Encoding Benchmark

## What is this project?

The Crowdsourced Video Encoding Benchmark is a community-driven platform designed to solve a common and complex problem for video creators, developers, and enthusiasts: **finding the best video encoding settings for specific hardware.**

Modern video encoding is filled with countless codecs (like H.264, HEVC/H.265, AV1), presets, and hardware acceleration options. The optimal choice depends entirely on the user's specific CPU and GPU, and finding the right balance between quality, speed, and file size often requires hours of trial-and-error.

This project eliminates the guesswork by creating a public, centralized database of real-world performance metrics, populated by users from around the world.

### The Problem It Solves

* **"What are the fastest encoding settings for my RTX 4070?"**
* **"Will I get better quality using my CPU (x265) or my GPU (NVENC)?"**
* **"For my Ryzen 9 7950X, what's the quality difference between the 'medium' and 'slow' presets, and is it worth the extra time?"**
* **"I need the smallest possible file size with a VMAF score above 95. What's the best preset for that?"**

Our platform provides direct, data-driven answers to these questions.

### Core Components

The project consists of three main parts working together:

1.  **The Benchmarking Client:** A simple, cross-platform application that users download. It automatically detects their hardware (CPU, GPU, RAM), runs a series of standardized `ffmpeg` encoding tests, and securely uploads the results (encoding speed, VMAF quality score, file size) to our central database.
2.  **The Central Database:** A robust backend system that collects, validates, and organizes all the performance data submitted by users.
3.  **The Public Web Interface:** An intuitive, user-friendly website where anyone can search, filter, and compare the benchmark data. Users can easily find their hardware and see clear performance charts to make informed decisions.

---

## The Intended User Flow

We envision two primary ways users will interact with the platform: contributing data and exploring data.

### Flow 1: The Contributor (Helping Build the Database)

This user has hardware they are willing to test to help the community. Their journey is simple and automated.

1.  **Discover & Download:** The user lands on the project website, reads about the mission, and navigates to the "Contribute" page. They download the benchmarking client for their operating system (Windows, macOS, or Linux).
2.  **Run the Benchmark:** The user runs the downloaded application. There are no complex settings to configure. The client displays a simple interface showing its progress.
3.  **Automatic Testing:** The client takes over. It automatically:
    * Identifies the user's CPU, GPU, RAM, and OS.
    * Downloads a standard source video file.
    * Runs a series of pre-defined `ffmpeg` transcode tests.
    * Measures the performance (FPS), quality (VMAF), and file size for each test.
4.  **Submit Results:** Once the tests are complete, the client packages all the results and hardware information into a JSON file and automatically submits it to the central server.
5.  **Confirmation:** The client shows a "Submission Successful!" message. The user has now successfully contributed valuable data to the project with minimal effort.

### Flow 2: The Data Explorer (Finding the Best Settings)

This user is a content creator or developer who needs to encode a video and wants to find the most efficient settings for their machine *before* starting a long render.

1.  **Visit the Website:** The user navigates to the homepage with a specific goal in mind, such as "find the best HEVC preset for my AMD Radeon RX 7900 XTX."
2.  **Search & Filter:** The user utilizes the powerful search and filtering tools on the "Database Explorer" page. They can filter by:
    * CPU Model
    * GPU Model
    * Codec (e.g., `libx265`, `h264_nvenc`)
3.  **Analyze the Results:** The website displays a clean, sortable table of relevant benchmarks. The user can sort the results to find what matters most to them:
    * **Sort by VMAF Score (descending)** to find the highest-quality settings.
    * **Sort by Encoding FPS (descending)** to find the fastest settings.
    * **Sort by File Size (ascending)** to find the most space-efficient settings.
4.  **Visualize Performance:** Alongside the table, interactive charts visualize the trade-offs. For example, a bar chart might show how FPS drops as the user moves from the `fast` to the `slow` preset, while another line chart shows the corresponding increase in VMAF score.
5.  **Make an Informed Decision:** Within minutes, the user has a clear, data-backed answer. They now know the exact `ffmpeg` preset that will give them the ideal balance of quality, speed, and file size for their specific hardware and can proceed with their own video projects confidently.