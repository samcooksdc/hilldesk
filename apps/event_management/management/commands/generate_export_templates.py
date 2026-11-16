# SPDX-License-Identifier: Apache-2.0
"""
Management command to generate built-in .docx export templates.

Uses python-docx to programmatically create Word documents containing
docxtpl Jinja2 placeholder syntax. These are the default templates
shipped with HillDesk.

IMPORTANT: docxtpl {%tr} tags replace the ENTIRE <w:tr> element they
reside in. Therefore {%tr for ...%} and {%tr endfor %} must each be
in their OWN dedicated table row, separate from the data row.

Correct pattern:
  Row 0: Header row
  Row 1: {%tr for <var> in <iterable> %}   ← dedicated row (removed at render)
  Row 2: {{ var.field1 }} | {{ var.field2 }}  ← data row (repeated)
  Row 3: {%tr endfor %}                      ← dedicated row (removed at render)

Usage:
    python manage.py generate_export_templates
"""

import os
from django.core.management.base import BaseCommand
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT


class Command(BaseCommand):
    help = 'Generate built-in .docx export templates for HillDesk'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            type=str,
            default=None,
            help='Output directory for templates (default: event_management/templates_docx/)',
        )

    def handle(self, *args, **options):
        output_dir = options['output_dir']
        if not output_dir:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            output_dir = os.path.join(base, 'templates_docx')

        os.makedirs(output_dir, exist_ok=True)

        self._generate_daily_briefing(output_dir)
        self._generate_weekly_overview(output_dir)
        self._generate_event_detail(output_dir)
        self._generate_filtered_list(output_dir)

        self.stdout.write(self.style.SUCCESS(
            f'Generated 4 export templates in {output_dir}'
        ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_cell_text(self, cell, text: str, bold: bool = False, size: int = 10):
        """Set text in a table cell with formatting, keeping it in a single XML run."""
        cell.text = ''
        p = cell.paragraphs[0]
        run = p.add_run(text)
        run.font.size = Pt(size)
        run.bold = bold
        run.font.name = 'Times New Roman'

    def _set_cell_jinja(self, cell, tag: str):
        """
        Write a Jinja2/docxtpl tag as the sole content of a cell.
        Ensures the tag stays in a single XML <w:t> element with
        xml:space="preserve" so docxtpl can find it.
        """
        cell.text = ''
        p = cell.paragraphs[0]
        run = p.add_run(tag)
        # Force xml:space="preserve" on the <w:t> element
        t_elements = run._element.findall(
            './/{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'
        )
        if t_elements:
            t_elements[0].set(
                '{http://www.w3.org/XML/1998/namespace}space', 'preserve'
            )
        run.font.size = Pt(1)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    def _add_heading_block(self, doc, office_line: str, title: str):
        """Add standard header block used by multi-event templates."""
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(office_line)
        run.font.size = Pt(14)
        run.bold = True
        run.font.name = 'Times New Roman'

        p2 = doc.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run2 = p2.add_run(title)
        run2.font.size = Pt(12)
        run2.font.name = 'Calibri'

    def _add_loop_table(self, doc, headers, data_placeholders, loop_tag):
        """
        Add a table with a docxtpl row loop.

        Creates:
          Row 0: Header row
          Row 1: {%tr for <var> in <iterable> %} — dedicated row (removed at render)
          Row 2: Data placeholders (this row is repeated per iteration)
          Row 3: {%tr endfor %} — dedicated row (removed at render)
        """
        num_cols = len(headers)
        table = doc.add_table(rows=1, cols=num_cols)
        table.style = 'Table Grid'
        table.alignment = WD_TABLE_ALIGNMENT.CENTER

        # Row 0: Header row
        for i, h in enumerate(headers):
            self._set_cell_text(table.rows[0].cells[i], h, bold=True)

        # Row 1: {%tr for ... %} — dedicated loop-start row
        loop_row = table.add_row()
        self._set_cell_jinja(loop_row.cells[0], loop_tag)

        # Row 2: Data row with placeholders
        data_row = table.add_row()
        for i, placeholder in enumerate(data_placeholders):
            if i < num_cols:
                self._set_cell_text(data_row.cells[i], placeholder)

        # Row 3: {%tr endfor %} — dedicated loop-end row
        endfor_row = table.add_row()
        self._set_cell_jinja(endfor_row.cells[0], '{%tr endfor %}')

        return table

    # ------------------------------------------------------------------
    # Daily Briefing
    # ------------------------------------------------------------------

    def _generate_daily_briefing(self, output_dir: str):
        doc = Document()

        style = doc.styles['Normal']
        style.font.name = 'Times New Roman'
        style.font.size = Pt(10)

        # Header
        self._add_heading_block(doc, '{{ office_name }}', 'Daily Scheduling Briefing')

        # Memo block
        memo = doc.add_paragraph()
        memo.add_run('TO:      ').bold = True
        memo.add_run('{{ member_name }}')
        memo.add_run('\n')
        memo.add_run('FROM:    ').bold = True
        memo.add_run('Scheduling Office')
        memo.add_run('\n')
        memo.add_run('DATE:    ').bold = True
        memo.add_run('{{ date_formatted }}')
        memo.add_run('\n')
        memo.add_run('RE:      ').bold = True
        memo.add_run("Today's Schedule — {{ event_count }} event(s)")

        doc.add_paragraph('')

        # Event table
        self._add_loop_table(
            doc,
            headers=['Time', 'Title', 'Location', 'Staff', 'Notes'],
            data_placeholders=[
                '{{ event.time_display }}',
                '{{ event.title }}',
                '{{ event.location }}',
                '{{ event.staff_csv }}',
                '{{ event.notes_short }}',
            ],
            loop_tag='{%tr for event in events %}',
        )

        doc.add_paragraph('')
        p_footer = doc.add_paragraph()
        p_footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        run_f = p_footer.add_run('Generated {{ generated_at }}')
        run_f.font.size = Pt(8)
        run_f.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

        doc.save(os.path.join(output_dir, 'daily_briefing.docx'))
        self.stdout.write('  Created daily_briefing.docx')

    # ------------------------------------------------------------------
    # Weekly Overview
    # ------------------------------------------------------------------

    def _generate_weekly_overview(self, output_dir: str):
        doc = Document()

        style = doc.styles['Normal']
        style.font.name = 'Times New Roman'
        style.font.size = Pt(10)

        self._add_heading_block(doc, '{{ office_name }}', 'Weekly Schedule Overview')

        p_range = doc.add_paragraph()
        p_range.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_r = p_range.add_run('{{ date_range }}')
        run_r.font.size = Pt(10)
        run_r.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

        doc.add_paragraph('')

        # Day loop (paragraph-level)
        p_loop_start = doc.add_paragraph('{%p for day in days %}')
        p_loop_start.runs[0].font.size = Pt(1)
        p_loop_start.runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        day_heading = doc.add_paragraph()
        run_day = day_heading.add_run('{{ day.label }}')
        run_day.bold = True
        run_day.font.size = Pt(12)

        day_sub = doc.add_paragraph()
        run_sub = day_sub.add_run('{{ day.event_count }} event(s)')
        run_sub.font.size = Pt(9)
        run_sub.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

        # Events table within each day
        self._add_loop_table(
            doc,
            headers=['Time', 'Title', 'Location', 'Status', 'Staff'],
            data_placeholders=[
                '{{ event.time_display }}',
                '{{ event.title }}',
                '{{ event.location }}',
                '{{ event.status_display }}',
                '{{ event.staff_csv }}',
            ],
            loop_tag='{%tr for event in day.events %}',
        )

        doc.add_paragraph('')

        p_loop_end = doc.add_paragraph('{%p endfor %}')
        p_loop_end.runs[0].font.size = Pt(1)
        p_loop_end.runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        # Summary line
        p_summary = doc.add_paragraph()
        run_s = p_summary.add_run('Total: {{ event_count }} events across {{ day_count }} days')
        run_s.font.size = Pt(10)
        run_s.bold = True

        p_footer = doc.add_paragraph()
        p_footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        run_f = p_footer.add_run('Generated {{ generated_at }}')
        run_f.font.size = Pt(8)
        run_f.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

        doc.save(os.path.join(output_dir, 'weekly_overview.docx'))
        self.stdout.write('  Created weekly_overview.docx')

    # ------------------------------------------------------------------
    # Event Detail (no table loops — single event)
    # ------------------------------------------------------------------

    def _generate_event_detail(self, output_dir: str):
        doc = Document()

        style = doc.styles['Normal']
        style.font.name = 'Times New Roman'
        style.font.size = Pt(10)

        # Large title
        p_title = doc.add_paragraph()
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_t = p_title.add_run('{{ event.title }}')
        run_t.font.size = Pt(18)
        run_t.bold = True

        p_status = doc.add_paragraph()
        p_status.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_st = p_status.add_run('Status: {{ event.status_display }}')
        run_st.font.size = Pt(12)

        doc.add_paragraph('')

        # Two-column metadata table (no loops)
        meta_table = doc.add_table(rows=9, cols=2)
        meta_table.style = 'Table Grid'

        fields = [
            ('Type', '{{ event.type_display }}'),
            ('Date', '{{ event.start_date_formatted }}'),
            ('Time', '{{ event.time_display }}'),
            ('Duration', '{{ event.duration }}'),
            ('Location', '{{ event.location }}'),
            ('Group / Requester', '{{ event.group }}'),
            ('Point of Contact', '{{ event.point_of_contact_name }}'),
            ('Contact Email', '{{ event.point_of_contact_email }}'),
            ('Tags', '{{ event.tags_csv }}'),
        ]
        for i, (label, placeholder) in enumerate(fields):
            self._set_cell_text(meta_table.rows[i].cells[0], label, bold=True)
            self._set_cell_text(meta_table.rows[i].cells[1], placeholder)

        doc.add_paragraph('')

        # Staff section
        p_staff_h = doc.add_paragraph()
        run_sh = p_staff_h.add_run('Assigned Staff')
        run_sh.bold = True
        run_sh.font.size = Pt(12)
        doc.add_paragraph('{{ event.staff_csv }}')

        # Description section
        p_desc_h = doc.add_paragraph()
        run_dh = p_desc_h.add_run('Description')
        run_dh.bold = True
        run_dh.font.size = Pt(12)
        doc.add_paragraph('{{ event.description }}')

        # Notes section
        p_notes_h = doc.add_paragraph()
        run_nh = p_notes_h.add_run('Notes')
        run_nh.bold = True
        run_nh.font.size = Pt(12)
        doc.add_paragraph('{{ event.notes }}')

        # Routing trail section (has loop)
        p_routing_h = doc.add_paragraph()
        run_rh = p_routing_h.add_run('Routing Trail')
        run_rh.bold = True
        run_rh.font.size = Pt(12)

        self._add_loop_table(
            doc,
            headers=['Who', 'Action', 'When'],
            data_placeholders=[
                '{{ step.who }}',
                '{{ step.action }}',
                '{{ step.when }}',
            ],
            loop_tag='{%tr for step in routing_trail %}',
        )

        doc.add_paragraph('')

        # Source email section (no loops)
        p_email_h = doc.add_paragraph()
        run_eh = p_email_h.add_run('Source Email')
        run_eh.bold = True
        run_eh.font.size = Pt(12)

        email_table = doc.add_table(rows=3, cols=2)
        email_table.style = 'Table Grid'
        email_fields = [
            ('From', '{{ source_email.sender }}'),
            ('Subject', '{{ source_email.subject }}'),
            ('Date', '{{ source_email.date }}'),
        ]
        for i, (label, placeholder) in enumerate(email_fields):
            self._set_cell_text(email_table.rows[i].cells[0], label, bold=True)
            self._set_cell_text(email_table.rows[i].cells[1], placeholder)

        doc.add_paragraph('{{ source_email.body_snippet }}')

        # Footer
        p_footer = doc.add_paragraph()
        p_footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        run_f = p_footer.add_run('Generated {{ generated_at }} — {{ office_name }}')
        run_f.font.size = Pt(8)
        run_f.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

        doc.save(os.path.join(output_dir, 'event_detail.docx'))
        self.stdout.write('  Created event_detail.docx')

    # ------------------------------------------------------------------
    # Filtered List
    # ------------------------------------------------------------------

    def _generate_filtered_list(self, output_dir: str):
        doc = Document()

        style = doc.styles['Normal']
        style.font.name = 'Times New Roman'
        style.font.size = Pt(10)

        self._add_heading_block(doc, '{{ office_name }}', 'Event List')

        # Active filters line
        p_filters = doc.add_paragraph()
        run_fl = p_filters.add_run('Filters: {{ active_filters_display }}')
        run_fl.font.size = Pt(9)
        run_fl.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

        doc.add_paragraph('')

        # Event table
        self._add_loop_table(
            doc,
            headers=['Date', 'Time', 'Title', 'Group', 'Location', 'Status', 'Staff'],
            data_placeholders=[
                '{{ event.start_date_formatted }}',
                '{{ event.time_display }}',
                '{{ event.title }}',
                '{{ event.group }}',
                '{{ event.location }}',
                '{{ event.status_display }}',
                '{{ event.staff_csv }}',
            ],
            loop_tag='{%tr for event in events %}',
        )

        doc.add_paragraph('')

        # Footer
        p_count = doc.add_paragraph()
        run_c = p_count.add_run('Total: {{ event_count }} event(s)')
        run_c.bold = True

        p_footer = doc.add_paragraph()
        p_footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        run_f = p_footer.add_run('Generated {{ generated_at }}')
        run_f.font.size = Pt(8)
        run_f.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

        doc.save(os.path.join(output_dir, 'filtered_list.docx'))
        self.stdout.write('  Created filtered_list.docx')
