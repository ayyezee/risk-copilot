"""Document generation service for creating DOCX output with formatting preservation.

This service handles:
1. DOCX input: Preserves original formatting while applying replacements
2. PDF input: Creates clean DOCX from extracted text
3. Track changes: Generates a changes report document
"""

import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

import structlog
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from app.services.document_ai_processor import TermReplacement

logger = structlog.get_logger()


@dataclass
class ReplacementMatch:
    """Tracks a single replacement occurrence in the document."""
    original_term: str
    replacement_term: str
    paragraph_index: int
    location_description: str
    reasoning: str
    confidence: float


@dataclass
class GenerationResult:
    """Result of document generation."""
    output_bytes: bytes
    output_filename: str
    content_type: str
    total_replacements_applied: int
    replacement_details: list[ReplacementMatch] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_format: str = "docx"  # "docx" or "pdf"


class DocumentGenerator:
    """Generates DOCX documents with applied replacements while preserving formatting."""

    def __init__(self) -> None:
        self.logger = structlog.get_logger()

    def apply_replacements_to_docx(
        self,
        input_file: BinaryIO,
        replacements: list[TermReplacement],
        case_sensitive: bool = False,
        highlight_changes: bool = True,
        min_confidence: float = 0.7,
    ) -> GenerationResult:
        """Apply term replacements to a DOCX file while preserving formatting.

        Args:
            input_file: File-like object containing the original DOCX
            replacements: List of term replacements to apply
            case_sensitive: Whether to match case-sensitively
            highlight_changes: Whether to highlight replaced text
            min_confidence: Minimum confidence threshold for applying replacements

        Returns:
            GenerationResult with the modified document
        """
        # Filter replacements by confidence
        applicable_replacements = [
            r for r in replacements if r.confidence >= min_confidence
        ]

        # Sort by original term length (longest first) to avoid partial replacements
        applicable_replacements.sort(key=lambda r: len(r.original_term), reverse=True)

        # Load the document
        doc = Document(input_file)

        replacement_matches: list[ReplacementMatch] = []
        total_replacements = 0

        # Process main document body paragraphs
        for para_idx, paragraph in enumerate(doc.paragraphs):
            count, matches = self._apply_replacements_to_paragraph(
                paragraph=paragraph,
                replacements=applicable_replacements,
                case_sensitive=case_sensitive,
                highlight_changes=highlight_changes,
                para_index=para_idx,
                location="body",
            )
            total_replacements += count
            replacement_matches.extend(matches)

        # Process tables
        for table_idx, table in enumerate(doc.tables):
            for row_idx, row in enumerate(table.rows):
                for cell_idx, cell in enumerate(row.cells):
                    for para_idx, paragraph in enumerate(cell.paragraphs):
                        count, matches = self._apply_replacements_to_paragraph(
                            paragraph=paragraph,
                            replacements=applicable_replacements,
                            case_sensitive=case_sensitive,
                            highlight_changes=highlight_changes,
                            para_index=para_idx,
                            location=f"table {table_idx + 1}, row {row_idx + 1}, cell {cell_idx + 1}",
                        )
                        total_replacements += count
                        replacement_matches.extend(matches)

        # Process headers
        for section in doc.sections:
            for header_type in ['header', 'first_page_header', 'even_page_header']:
                header = getattr(section, header_type, None)
                if header:
                    for para_idx, paragraph in enumerate(header.paragraphs):
                        count, matches = self._apply_replacements_to_paragraph(
                            paragraph=paragraph,
                            replacements=applicable_replacements,
                            case_sensitive=case_sensitive,
                            highlight_changes=highlight_changes,
                            para_index=para_idx,
                            location=f"{header_type}",
                        )
                        total_replacements += count
                        replacement_matches.extend(matches)

            # Process footers
            for footer_type in ['footer', 'first_page_footer', 'even_page_footer']:
                footer = getattr(section, footer_type, None)
                if footer:
                    for para_idx, paragraph in enumerate(footer.paragraphs):
                        count, matches = self._apply_replacements_to_paragraph(
                            paragraph=paragraph,
                            replacements=applicable_replacements,
                            case_sensitive=case_sensitive,
                            highlight_changes=highlight_changes,
                            para_index=para_idx,
                            location=f"{footer_type}",
                        )
                        total_replacements += count
                        replacement_matches.extend(matches)

        # Save to bytes
        output_buffer = io.BytesIO()
        doc.save(output_buffer)
        output_buffer.seek(0)

        self.logger.info(
            "DOCX generation complete",
            total_replacements=total_replacements,
            unique_terms_replaced=len(set(m.original_term for m in replacement_matches)),
        )

        return GenerationResult(
            output_bytes=output_buffer.getvalue(),
            output_filename=f"processed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            total_replacements_applied=total_replacements,
            replacement_details=replacement_matches,
            source_format="docx",
        )

    def _apply_replacements_to_paragraph(
        self,
        paragraph: Paragraph,
        replacements: list[TermReplacement],
        case_sensitive: bool,
        highlight_changes: bool,
        para_index: int,
        location: str,
    ) -> tuple[int, list[ReplacementMatch]]:
        """Apply replacements to a single paragraph while preserving run formatting.

        This method handles the complex case where a term to replace might span
        multiple runs (e.g., "the <b>vendor</b>" where "vendor" is bold).

        Args:
            paragraph: The paragraph to process
            replacements: Replacements to apply
            case_sensitive: Whether to match case-sensitively
            highlight_changes: Whether to highlight changes
            para_index: Index of the paragraph
            location: Description of where this paragraph is

        Returns:
            Tuple of (replacement count, list of matches)
        """
        if not paragraph.runs:
            return 0, []

        # Get the full paragraph text
        full_text = paragraph.text
        if not full_text.strip():
            return 0, []

        total_count = 0
        matches: list[ReplacementMatch] = []

        # Process each replacement
        for replacement in replacements:
            flags = 0 if case_sensitive else re.IGNORECASE
            pattern = re.compile(
                r'\b' + re.escape(replacement.original_term) + r'\b',
                flags
            )

            # Check if the term exists in this paragraph
            if not pattern.search(full_text):
                continue

            # Apply the replacement using the run-aware method
            count = self._replace_in_paragraph_runs(
                paragraph=paragraph,
                pattern=pattern,
                replacement_text=replacement.replacement_term,
                highlight=highlight_changes,
            )

            if count > 0:
                total_count += count
                matches.append(ReplacementMatch(
                    original_term=replacement.original_term,
                    replacement_term=replacement.replacement_term,
                    paragraph_index=para_index,
                    location_description=location,
                    reasoning=replacement.reasoning,
                    confidence=replacement.confidence,
                ))

            # Update full_text for next iteration
            full_text = paragraph.text

        return total_count, matches

    def _replace_in_paragraph_runs(
        self,
        paragraph: Paragraph,
        pattern: re.Pattern,
        replacement_text: str,
        highlight: bool,
    ) -> int:
        """Replace text in paragraph runs while preserving formatting.

        This handles the case where the text to replace spans multiple runs.

        Args:
            paragraph: The paragraph to modify
            pattern: Compiled regex pattern for matching
            replacement_text: Text to replace matches with
            highlight: Whether to highlight the replacement

        Returns:
            Number of replacements made
        """
        # Build a map of character positions to runs
        runs = paragraph.runs
        if not runs:
            return 0

        # Concatenate all run texts and track boundaries
        full_text = ""
        run_boundaries = []  # List of (start, end, run_index)

        for i, run in enumerate(runs):
            start = len(full_text)
            full_text += run.text
            end = len(full_text)
            run_boundaries.append((start, end, i))

        # Find all matches
        matches = list(pattern.finditer(full_text))
        if not matches:
            return 0

        # Process matches in reverse order to preserve positions
        for match in reversed(matches):
            match_start = match.start()
            match_end = match.end()

            # Find which runs this match spans
            affected_runs = []
            for start, end, run_idx in run_boundaries:
                if start < match_end and end > match_start:
                    # Calculate the portion of this run that's affected
                    local_start = max(0, match_start - start)
                    local_end = min(end - start, match_end - start)
                    affected_runs.append((run_idx, local_start, local_end))

            if not affected_runs:
                continue

            # Handle single-run case (most common)
            if len(affected_runs) == 1:
                run_idx, local_start, local_end = affected_runs[0]
                run = runs[run_idx]
                old_text = run.text
                new_text = old_text[:local_start] + replacement_text + old_text[local_end:]
                run.text = new_text

                if highlight:
                    self._highlight_run(run)

            else:
                # Multi-run case: put replacement in first run, clear others
                first_run_idx, first_local_start, first_local_end = affected_runs[0]
                first_run = runs[first_run_idx]

                # Preserve formatting from first run
                old_text = first_run.text
                first_run.text = old_text[:first_local_start] + replacement_text

                if highlight:
                    self._highlight_run(first_run)

                # Clear the matched portions from subsequent runs
                for run_idx, local_start, local_end in affected_runs[1:]:
                    run = runs[run_idx]
                    old_text = run.text
                    # Keep text before and after the match portion
                    run.text = old_text[:local_start] + old_text[local_end:]

                # Handle text after the match in the last affected run
                last_run_idx, last_local_start, last_local_end = affected_runs[-1]
                if last_run_idx != first_run_idx:
                    last_run = runs[last_run_idx]
                    # Text after match is already preserved from the clear step above

        # Recalculate boundaries and return count
        return len(matches)

    def _highlight_run(self, run: Run) -> None:
        """Apply yellow highlight to a run to mark it as changed."""
        run.font.highlight_color = WD_COLOR_INDEX.YELLOW

    def create_docx_from_text(
        self,
        text: str,
        replacements: list[TermReplacement],
        original_filename: str,
        case_sensitive: bool = False,
        highlight_changes: bool = True,
        min_confidence: float = 0.7,
    ) -> GenerationResult:
        """Create a DOCX document from plain text (e.g., extracted from PDF).

        This is used when the original format can't preserve formatting (PDF).

        Args:
            text: The extracted text content
            replacements: List of term replacements to apply
            original_filename: Name of the original file
            case_sensitive: Whether to match case-sensitively
            highlight_changes: Whether to highlight replaced text
            min_confidence: Minimum confidence threshold

        Returns:
            GenerationResult with the new document
        """
        # Filter replacements by confidence
        applicable_replacements = [
            r for r in replacements if r.confidence >= min_confidence
        ]
        applicable_replacements.sort(key=lambda r: len(r.original_term), reverse=True)

        # Create a new document
        doc = Document()

        # Add a header noting this is a conversion
        header_para = doc.add_paragraph()
        header_run = header_para.add_run(
            f"Converted from: {original_filename}\n"
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Note: Original formatting could not be preserved."
        )
        header_run.font.size = Pt(9)
        header_run.font.italic = True
        header_run.font.color.rgb = RGBColor(128, 128, 128)

        doc.add_paragraph()  # Spacer

        # Apply replacements to the text
        modified_text = text
        replacement_matches: list[ReplacementMatch] = []
        total_replacements = 0

        for replacement in applicable_replacements:
            flags = 0 if case_sensitive else re.IGNORECASE
            pattern = re.compile(
                r'\b' + re.escape(replacement.original_term) + r'\b',
                flags
            )

            matches = list(pattern.finditer(modified_text))
            if matches:
                modified_text = pattern.sub(replacement.replacement_term, modified_text)
                total_replacements += len(matches)
                replacement_matches.append(ReplacementMatch(
                    original_term=replacement.original_term,
                    replacement_term=replacement.replacement_term,
                    paragraph_index=0,
                    location_description="document body",
                    reasoning=replacement.reasoning,
                    confidence=replacement.confidence,
                ))

        # Add the text as paragraphs (split on double newlines)
        paragraphs = modified_text.split('\n\n')
        for para_text in paragraphs:
            if para_text.strip():
                # Handle single newlines within the paragraph
                lines = para_text.split('\n')
                para = doc.add_paragraph()
                for i, line in enumerate(lines):
                    if i > 0:
                        para.add_run('\n')
                    run = para.add_run(line)

                    # If highlighting, we need to check if this line contains replacements
                    if highlight_changes:
                        for rep in applicable_replacements:
                            if rep.replacement_term.lower() in line.lower():
                                run.font.highlight_color = WD_COLOR_INDEX.YELLOW
                                break

        # Save to bytes
        output_buffer = io.BytesIO()
        doc.save(output_buffer)
        output_buffer.seek(0)

        warnings = [
            "Original document was PDF - formatting could not be preserved.",
            "Document has been converted to a clean DOCX format.",
        ]

        self.logger.info(
            "PDF-to-DOCX conversion complete",
            total_replacements=total_replacements,
            original_file=original_filename,
        )

        return GenerationResult(
            output_bytes=output_buffer.getvalue(),
            output_filename=f"converted_{Path(original_filename).stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            total_replacements_applied=total_replacements,
            replacement_details=replacement_matches,
            warnings=warnings,
            source_format="pdf",
        )

    def generate_changes_report(
        self,
        replacement_matches: list[ReplacementMatch],
        original_filename: str,
        document_summary: str | None = None,
    ) -> GenerationResult:
        """Generate a separate document detailing all changes made.

        This serves as an audit trail and review document.

        Args:
            replacement_matches: All replacements that were applied
            original_filename: Name of the original file
            document_summary: Optional AI-generated summary

        Returns:
            GenerationResult with the changes report document
        """
        doc = Document()

        # Title
        title = doc.add_heading("Document Changes Report", level=0)

        # Metadata section
        doc.add_heading("Document Information", level=1)
        info_table = doc.add_table(rows=3, cols=2)
        info_table.style = 'Table Grid'

        cells = info_table.rows[0].cells
        cells[0].text = "Original File"
        cells[1].text = original_filename

        cells = info_table.rows[1].cells
        cells[0].text = "Processed Date"
        cells[1].text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cells = info_table.rows[2].cells
        cells[0].text = "Total Replacements"
        cells[1].text = str(len(replacement_matches))

        doc.add_paragraph()  # Spacer

        # Summary section
        if document_summary:
            doc.add_heading("Summary", level=1)
            doc.add_paragraph(document_summary)

        # Changes detail section
        doc.add_heading("Detailed Changes", level=1)

        if not replacement_matches:
            doc.add_paragraph("No replacements were applied to this document.")
        else:
            # Group by original term
            from collections import defaultdict
            grouped = defaultdict(list)
            for match in replacement_matches:
                grouped[match.original_term].append(match)

            for original_term, matches in grouped.items():
                # Term header
                term_para = doc.add_paragraph()
                term_run = term_para.add_run(f"'{original_term}' → '{matches[0].replacement_term}'")
                term_run.bold = True
                term_run.font.size = Pt(12)

                # Reasoning
                reason_para = doc.add_paragraph()
                reason_para.add_run("Reasoning: ").bold = True
                reason_para.add_run(matches[0].reasoning)

                # Confidence
                conf_para = doc.add_paragraph()
                conf_para.add_run("Confidence: ").bold = True
                confidence_pct = f"{matches[0].confidence * 100:.0f}%"
                conf_para.add_run(confidence_pct)

                # Locations
                locations = list(set(m.location_description for m in matches))
                if locations:
                    loc_para = doc.add_paragraph()
                    loc_para.add_run("Locations: ").bold = True
                    loc_para.add_run(", ".join(locations))

                doc.add_paragraph()  # Spacer between terms

        # Save to bytes
        output_buffer = io.BytesIO()
        doc.save(output_buffer)
        output_buffer.seek(0)

        return GenerationResult(
            output_bytes=output_buffer.getvalue(),
            output_filename=f"changes_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            total_replacements_applied=len(replacement_matches),
            replacement_details=replacement_matches,
            source_format="report",
        )


# Singleton instance
_document_generator_instance: DocumentGenerator | None = None


def get_document_generator() -> DocumentGenerator:
    """Get document generator singleton instance."""
    global _document_generator_instance
    if _document_generator_instance is None:
        _document_generator_instance = DocumentGenerator()
    return _document_generator_instance
