---
applyTo: 'library/*/chapters/*.md'
---

**AI Agent Instructions: Generate Book Chapter Markdown File**

Given a chapter title and summary, produce a Markdown file for the chapter with the following structure and content:

1. **Front Matter**
   - Add YAML front matter with:
     - `title`: The chapter’s title.
     - `subtitle`: A short phrase capturing the chapter’s theme or focus.
     - `character`: Main character(s) featured in the chapter.
     - `setting`: The primary location(s) of the chapter.
     - `era`: The time period or year(s) in which the chapter takes place.
     - `tone`: The emotional tone or style (e.g., Satirical, Somber, Hopeful).
     - `style`: The narrative style or point of view (e.g., First-Person, Observational).

2. **Outline and Contextual Alignment**
   - Add a section titled “Outline and Contextual Alignment” with:
     - **Purpose of the Chapter**: Bullet points describing the chapter’s narrative goals, character development, and thematic focus.
     - **Setting**: Bullet points describing the physical and social environment.
     - **Main Character**: Bullet points on the protagonist’s role, background, and traits.
     - **Plot Progression**: Numbered list of key scenes or beats, each with a brief description.
     - **Themes Introduced**: Bullet points listing the main themes or motifs that appear in this chapter.

3. **Chapter Body**
   - Add a section with the chapter’s narrative text, written in the specified style and tone. Use vivid details, character voice, and dialogue as appropriate.

4. **References & Contextual Alignment with Outline**
   - Add a section summarizing how the chapter’s content aligns with the outline and themes, referencing:
     - Emotional connection with the protagonist.
     - Legacy, setting, and company or world-building details.
     - Foreshadowing or callbacks to the main plot.
     - Key themes and motifs.
     - Plot progression and structure.

5. **Links and References**
   - At the end, add a section with Markdown links to:
     - The main README.md outline.
     - Previous and next chapter files (if applicable).
     - Any relevant external references or sources.

6. **Formatting**
   - Use Markdown headings, bullet points, and horizontal rules (`---`) as in the example.
   - Ensure each section is clearly labeled and easy to navigate.

**Output only the chapter Markdown file content. Do not include explanations or meta-comments.**