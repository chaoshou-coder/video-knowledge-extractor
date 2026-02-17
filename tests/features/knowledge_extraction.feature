Feature: Video Knowledge Extraction Pipeline
  As a user who wants to learn from video lectures
  I want to extract structured knowledge from video subtitles
  So that I can generate a textbook for efficient learning

  Background:
    Given the knowledge extraction system is initialized
    And I have valid API credentials configured

  # ==========================================
  # Stage 1: Document Processing
  # ==========================================

  Scenario: Process a single SRT file
    Given I have a subtitle file "lecture.srt" with the following content:
      """
      1
      00:00:01,000 --> 00:00:05,000
      Today we will learn about derivatives

      2
      00:00:05,000 --> 00:00:10,000
      A derivative measures the rate of change
      """
    When I process the file with the extraction pipeline
    Then the processing should complete successfully
    And I should get at least 1 knowledge point
    And the knowledge point should have a title
    And the knowledge point should have content

  Scenario: Clean noise from lecture content
    Given I have a document with filler words:
      """
      Um, today we will, uh, learn about calculus.
      So, you know, derivatives are important.
      Right? Let's see...
      """
    When I run the text cleaning stage
    Then the output should not contain "um"
    And the output should not contain "uh"
    And the output should not contain "you know"
    And the core content should be preserved

  Scenario: Extract structured knowledge points
    Given I have cleaned lecture content about "derivatives"
    When I run the knowledge extraction stage
    Then I should get knowledge points in JSON format
    And each point should have a "title" field
    And each point should have a "content" field
    And the content should contain relevant information about derivatives

  Scenario: Mark video references
    Given I have a knowledge point about "geometric interpretation"
    And the original subtitle mentioned "see this graph"
    When I run the video marking stage
    Then the output should contain a video marker
    And the marker should have a timestamp
    And the marker should describe the visual content

  # ==========================================
  # Stage 2: Cross-Document Processing
  # ==========================================

  Scenario: Process multiple documents in parallel
    Given I have a directory with 3 SRT files:
      | filename    | topic       |
      | lecture1.srt| Introduction|
      | lecture2.srt| Derivatives |
      | lecture3.srt| Applications|
    When I run batch processing with 2 workers
    Then all 3 files should be processed
    And the processing should complete within 60 seconds
    And I should get knowledge points from all files

  Scenario: Detect and merge duplicate knowledge points
    Given I have knowledge points from multiple files:
      | title               | content                           | source    |
      | Derivative Definition| The derivative is the rate of change| file1.srt |
      | Definition of Derivative| Derivative measures how a function changes| file2.srt |
      | Limit Concept       | Limit describes approaching values | file3.srt |
    When I run the knowledge fusion stage
    Then duplicate concepts should be merged
    And "Derivative Definition" and "Definition of Derivative" should become one point
    And "Limit Concept" should remain separate
    And the merged point should contain information from both sources

  Scenario: Generate course structure from topics
    Given I have the following knowledge points:
      | title                  | category    |
      | What is Calculus       | Introduction|
      | Limit Definition       | Foundation  |
      | Derivative Rules       | Methods     |
      | Chain Rule             | Methods     |
      | Optimization Examples  | Applications|
    When I run the clustering stage
    Then I should get a course structure with chapters
    And "Introduction" should be chapter 1
    And "Foundation" should come before "Methods"
    And "Applications" should be the last chapter

  # ==========================================
  # Stage 3: Textbook Generation
  # ==========================================

  Scenario: Generate Markdown textbook
    Given I have a course structure with 2 chapters:
      | order | title       | points_count |
      | 1     | Chapter 1   | 2            |
      | 2     | Chapter 2   | 3            |
    And I have transition paragraphs between chapters
    When I export to Markdown format
    Then the output should be a valid Markdown file
    And it should contain a table of contents
    And it should contain all chapters
    And it should contain transition text between chapters
    And video markers should be formatted as blockquotes

  Scenario: Generate HTML textbook
    Given I have a complete course structure
    When I export to HTML format
    Then the output should be a valid HTML file
    And it should have responsive CSS
    And it should have proper heading hierarchy
    And video references should be styled with CSS class

  Scenario: Generate EPUB textbook
    Given I have a complete course structure
    And the ebooklib library is installed
    When I export to EPUB format
    Then the output should be a valid EPUB file
    And it should contain NCX navigation
    And it should have chapter divisions

  # ==========================================
  # Error Handling
  # ==========================================

  Scenario: Handle empty directory
    Given I have an empty directory with no SRT files
    When I run batch processing
    Then the system should report "no files found"
    And the process should exit gracefully

  Scenario: Handle corrupted subtitle file
    Given I have a corrupted SRT file with invalid timestamps
    When I process the file
    Then the system should log an error
    And the processing should continue with other files
    And the corrupted file should be skipped

  Scenario: Handle API rate limiting
    Given the API is rate limited
    When I process documents
    Then the system should implement backoff
    And it should retry failed requests
    And after 3 retries it should use mock mode

  # ==========================================
  # End-to-End Workflow
  # ==========================================

  Scenario: Complete pipeline from SRT to textbook
    Given I have a directory with lecture subtitles
    When I run the complete pipeline:
      """
      kl batch ./lectures --build --format markdown
      """
    Then the processing should complete successfully
    And I should get a Markdown file
    And the file should contain structured knowledge
    And it should have video timestamps
    And it should have chapter transitions
    And the content should be free of filler words
