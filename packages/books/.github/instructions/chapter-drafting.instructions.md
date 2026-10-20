---
applyTo: 'library/*/chapters/*.md'
---

**AI Agent Instructions: Write or Update Book Chapter Based on Outline and Existing Chapters**

Given:
- The main book outline in README.md
- Existing chapter files in the book's `chapters/` directory
- The title or number of the chapter to be written or updated

Follow these steps:

1. **Review the Outline and Context**
   - Read the book's `outline.md` to understand the overall narrative structure, themes, character arcs, and suggested chapter titles.
   - Review the outlines and content of previously written chapters to ensure continuity, avoid repetition, and maintain consistent tone, style, and character development.

2. **Draft or Update the Specified Chapter**
   - For the specified chapter, create or update its Markdown file using the following structure:
     - **Front Matter**: YAML block with title, subtitle, character(s), setting, era, tone, and style.
     - **Outline and Contextual Alignment**: 
       - Purpose of the chapter (bullet points)
       - Setting (bullet points)
       - Main character(s) (bullet points)
       - Plot progression (numbered list)
       - Themes introduced (bullet points)
     - **Chapter Body**: Write the narrative in the specified style and tone, ensuring alignment with the outline and previous chapters.
     - **References & Contextual Alignment with Outline**: Summarize how the chapter aligns with the book’s outline, themes, and character arc.
     - **Links and References**: Add Markdown links to the main README.md, previous and next chapters, and any relevant sources.

3. **Cross-Reference and Suggest Minor Updates**
   - If the new or updated chapter introduces new information, characters, or events that affect earlier or later chapters, suggest concise updates to those chapters. Examples:
     - Add a callback, foreshadowing, or reference in a previous chapter.
     - Update a character’s background or motivation for consistency.
     - Adjust a theme or motif to maintain narrative coherence.
   - List these suggested updates at the end of your output, specifying the file and section to be updated, and a brief description of the change.

4. **Formatting**
   - Use Markdown headings, bullet points, and horizontal rules as in the existing chapters.
   - Ensure each section is clearly labeled and easy to navigate.

**Output only the new or updated chapter file content, followed by a list of suggested minor updates to other chapters (if any). Do not include explanations or meta-comments.**