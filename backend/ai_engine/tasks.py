import io
import json
from xml.sax.saxutils import escape

from django.utils import timezone
from ai_engine.models import InterviewSession
from ai_engine.brain import InterviewBrain

# ReportLab imports for beautiful PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER


def esc(value):
    """Plain text for a ReportLab Paragraph, which otherwise parses it as markup."""
    return escape(str(value))

def evaluate_transcript_semantic_gaps(session_id):
    """
    Compiles the transcript, evaluates semantic keyword coverage and technical depth
    vs target Job Description, and determines candidate competency scores.
    """
    try:
        session = InterviewSession.objects.get(id=session_id)
        app = session.application
        jd = app.job.description
        
        # Build raw transcript text
        transcript_text = ""
        for i, turn in enumerate(session.transcript, 1):
            q = turn.get('question', 'N/A')
            a = turn.get('answer', 'N/A')
            transcript_text += f"Round {i} - Question: {q}\nCandidate Response: {a}\n\n"
        
        # Call Groq LLM to evaluate transcript
        brain = InterviewBrain()
        
        # Holistically evaluate skills and identify gaps vs target JD
        skills_json = brain.get_session_skills(transcript_text, jd)
        skills = json.loads(skills_json)
        
        # Update session scores and isolated talent gaps
        session.tech_knowledge = skills.get('tech_knowledge', 70)
        session.behavioral_iq = skills.get('behavioral_iq', 70)
        session.problem_solving = skills.get('problem_solving', 70)
        session.gap_analysis = skills.get('gap_analysis', 'Assessment evaluation completed successfully.')
        session.save(update_fields=['tech_knowledge', 'behavioral_iq', 'problem_solving', 'gap_analysis'])
        
        return f"Successfully evaluated session {session_id}"
    except Exception as e:
        return f"Error evaluating session {session_id}: {str(e)}"

def compile_performance_report_pdf(session_id):
    """
    Collates the ATS Match Score, Proctoring Integrity Level, and Transcript Metrics,
    generating a beautifully styled ReportLab PDF.
    """
    try:
        session = InterviewSession.objects.get(id=session_id)
        app = session.application
        candidate = app.candidate
        job = app.job
        company = job.company
        
        pdf_buffer = io.BytesIO()
        
        # Setup document template
        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=letter,
            rightMargin=40,
            leftMargin=40,
            topMargin=40,
            bottomMargin=40
        )
        
        styles = getSampleStyleSheet()
        
        # Define clean, professional color palette (Deep slate blues, cool greys)
        primary_color = colors.HexColor('#1e3a8a')   # Navy Blue
        secondary_color = colors.HexColor('#3b82f6') # Light Blue
        accent_color = colors.HexColor('#10b981')    # Emerald Green
        dark_neutral = colors.HexColor('#1f2937')    # Dark Slate
        light_neutral = colors.HexColor('#f3f4f6')   # Soft Grey
        border_color = colors.HexColor('#e5e7eb')
        
        # Create ParagraphStyles
        title_style = ParagraphStyle(
            'DocTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=24,
            leading=28,
            textColor=primary_color,
            spaceAfter=4
        )
        
        subtitle_style = ParagraphStyle(
            'DocSub',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=10,
            leading=12,
            textColor=secondary_color,
            spaceAfter=20,
            textTransform='uppercase'
        )
        
        h2_style = ParagraphStyle(
            'SectionH2',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=14,
            leading=18,
            textColor=primary_color,
            spaceBefore=14,
            spaceAfter=8,
            keepWithNext=True
        )
        
        body_style = ParagraphStyle(
            'BodyNormal',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            leading=14,
            textColor=dark_neutral
        )
        
        meta_label_style = ParagraphStyle(
            'MetaLabel',
            parent=body_style,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#6b7280')
        )
        
        table_cell_style = ParagraphStyle(
            'TableCell',
            parent=body_style,
            fontSize=9,
            leading=12
        )
        
        table_cell_bold = ParagraphStyle(
            'TableCellBold',
            parent=table_cell_style,
            fontName='Helvetica-Bold'
        )
        
        round_header_style = ParagraphStyle(
            'RoundH',
            parent=styles['Heading3'],
            fontName='Helvetica-Bold',
            fontSize=11,
            leading=14,
            textColor=secondary_color,
            spaceBefore=10,
            spaceAfter=4,
            keepWithNext=True
        )
        
        speaker_ai_style = ParagraphStyle(
            'SpeakerAI',
            parent=body_style,
            fontName='Helvetica-Bold',
            textColor=secondary_color
        )
        
        speaker_candidate_style = ParagraphStyle(
            'SpeakerCand',
            parent=body_style,
            fontName='Helvetica-Bold',
            textColor=primary_color
        )
        
        story = []
        
        # --- TITLE BLOCK ---
        story.append(Paragraph("Hirely", title_style))
        story.append(Paragraph("Assessment Performance Profile", subtitle_style))
        
        # --- METADATA PANEL ---
        meta_data = [
            [
                Paragraph("Candidate Name:", meta_label_style),
                Paragraph(esc(candidate.username), body_style),
                Paragraph("Target Position:", meta_label_style),
                Paragraph(esc(job.title), body_style)
            ],
            [
                Paragraph("Email Address:", meta_label_style),
                Paragraph(esc(candidate.email), body_style),
                Paragraph("Company Hiring:", meta_label_style),
                Paragraph(esc(company.name), body_style)
            ],
            [
                Paragraph("Date Compiled:", meta_label_style),
                Paragraph(timezone.now().strftime('%B %d, %Y at %I:%M %p'), body_style),
                Paragraph("Assessment Status:", meta_label_style),
                Paragraph(app.get_status_display(), body_style)
            ]
        ]
        
        meta_table = Table(meta_data, colWidths=[110, 150, 110, 150])
        meta_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), light_neutral),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.white),
            ('BOX', (0,0), (-1,-1), 1, border_color),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ]))
        story.append(meta_table)
        story.append(Spacer(1, 15))
        
        # --- CORE METRICS PANEL ---
        story.append(Paragraph("Core Evaluation Metrics", h2_style))
        
        # Metrics scoring table
        metrics_data = [
            [
                Paragraph("Metric Category", ParagraphStyle('HCol', parent=meta_label_style, textColor=colors.white)),
                Paragraph("Rating", ParagraphStyle('HColR', parent=meta_label_style, textColor=colors.white, alignment=TA_CENTER))
            ],
        ]
        center = ParagraphStyle('Center', parent=table_cell_style, alignment=TA_CENTER)
        for label, value in [
            ("ATS Resume Proximity Match", app.ats_match_score if app.ats_match_score is not None else '--'),
            ("AI Proctoring Integrity Index", app.proctoring_score),
            ("Technical Knowledge Coverage", session.tech_knowledge),
            ("Behavioral & Collaboration IQ", session.behavioral_iq),
            ("Architectural Problem Solving", session.problem_solving),
            ("Average Speech Confidence", session.avg_confidence),
            ("Average Speech Clarity", session.avg_clarity),
        ]:
            metrics_data.append([Paragraph(label, table_cell_bold), Paragraph(f"{value}%", center)])
        
        metrics_table = Table(metrics_data, colWidths=[380, 140])
        metrics_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), primary_color),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, light_neutral]),
            ('BOX', (0,0), (-1,-1), 1, border_color),
            ('INNERGRID', (0,0), (-1,-1), 0.5, border_color),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ]))
        story.append(metrics_table)
        story.append(Spacer(1, 20))
        
        # --- PROCTORING VIOLATIONS AUDIT ---
        story.append(Paragraph("Security & Proctoring Audit Trail", h2_style))
        
        if session.proctoring_logs:
            proc_headers = [
                Paragraph("Anomaly Category", ParagraphStyle('HCol', parent=meta_label_style, textColor=colors.white)),
                Paragraph("Trigger Timestamp", ParagraphStyle('HCol', parent=meta_label_style, textColor=colors.white))
            ]
            proc_table_data = [proc_headers]
            for infraction in session.proctoring_logs:
                proc_table_data.append([
                    Paragraph(esc(infraction.get('type', 'Gaze Deviation')), table_cell_style),
                    Paragraph(esc(infraction.get('timestamp', '').replace('T', ' ')[:19]), table_cell_style)
                ])
            
            proc_table = Table(proc_table_data, colWidths=[280, 240])
            proc_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#dc2626')), # Alert Red Header
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#fee2e2')]), # Soft red alternate
                ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#fca5a5')),
                ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#fca5a5')),
                ('BOTTOMPADDING', (0,0), (-1,-1), 5),
                ('TOPPADDING', (0,0), (-1,-1), 5),
                ('LEFTPADDING', (0,0), (-1,-1), 10),
                ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ]))
            story.append(proc_table)
        else:
            story.append(Paragraph("<b>No security infractions flagged.</b> Edge-gaze proctoring verified total assessment integrity.", ParagraphStyle('SecOk', parent=body_style, textColor=accent_color)))

        # --- SKILLS GAP ANALYSIS ---
        if session.gap_analysis:
            story.append(Spacer(1, 20))
            story.append(Paragraph("Skills Gap Analysis", h2_style))
            story.append(Paragraph(esc(session.gap_analysis), body_style))
            
        story.append(PageBreak()) # Clean break to push transcripts onto secondary page
        
        # --- TRANSCRIPT DISPLAY ---
        story.append(Paragraph("Evaluation Chat Transcript", h2_style))
        
        for i, turn in enumerate(session.transcript, 1):
            q_text = turn.get('question', 'N/A')
            a_text = turn.get('answer', 'N/A')
            f_text = turn.get('feedback', '')
            
            round_flow = []
            round_flow.append(Paragraph(f"Round {i}", round_header_style))
            
            # AI Dialog
            round_flow.append(Paragraph("AI Interviewer:", speaker_ai_style))
            round_flow.append(Paragraph(esc(q_text), body_style))
            round_flow.append(Spacer(1, 4))
            
            # Candidate Dialog
            round_flow.append(Paragraph("Candidate:", speaker_candidate_style))
            round_flow.append(Paragraph(esc(a_text), body_style))
            round_flow.append(Spacer(1, 4))
            
            # Semantic Feedback block
            if f_text:
                round_flow.append(Paragraph("AI Constructive Feedback:", ParagraphStyle('AI_F', parent=body_style, fontName='Helvetica-Bold', textColor=accent_color)))
                round_flow.append(Paragraph(esc(f_text), ParagraphStyle('FeedbackP', parent=body_style, fontName='Helvetica-Oblique', textColor=colors.HexColor('#374151'))))
                
            round_flow.append(Spacer(1, 10))
            story.append(KeepTogether(round_flow))
            story.append(Spacer(1, 6))
            
        # Build Document
        doc.build(story)
        
        # Save compiled PDF bytes directly in InterviewSession
        session.pdf_report = pdf_buffer.getvalue()
        session.save(update_fields=['pdf_report'])
        
        return f"Successfully compiled PDF report for session {session_id}"
    except Exception as e:
        return f"Error compiling PDF for session {session_id}: {str(e)}"
