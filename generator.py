from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
import os
import base64

def generate_pptx(slides_data, output_path):
    prs = Presentation()
    
    # 0 = Title slide, 1 = Title and Content, 8 = Picture with caption (layouts vary, basic is 1)
    blank_slide_layout = prs.slide_layouts[1]
    
    for idx, slide_info in enumerate(slides_data):
        slide = prs.slides.add_slide(blank_slide_layout)
        shapes = slide.shapes
        
        # Title
        title_shape = shapes.title
        if title_shape:
            title_shape.text = slide_info.get("title", f"Slide {idx+1}")
            
        # Body
        body_shape = shapes.placeholders[1]
        text_frame = body_shape.text_frame
        
        bullets = slide_info.get("bullets", [])
        for i, bullet in enumerate(bullets):
            if i == 0:
                p = text_frame.paragraphs[0]
            else:
                p = text_frame.add_paragraph()
            p.text = bullet
            p.font.size = Pt(18)
            p.space_after = Pt(14)
            
        # Add image if available
        image_path = slide_info.get("image_path")
        if image_path and os.path.exists(image_path):
            try:
                # Place image on the right side
                left = Inches(5.5)
                top = Inches(2.0)
                height = Inches(4.5)
                slide.shapes.add_picture(image_path, left, top, height=height)
                # Ensure text frame doesn't overlap too much
                body_shape.width = Inches(5.0)
            except Exception as e:
                print(f"Error adding picture to PPTX: {e}")
                
    prs.save(output_path)
    return output_path

def get_image_base64(image_path):
    if not image_path or not os.path.exists(image_path):
        return None
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        _, ext = os.path.splitext(image_path)
        ext = ext.replace(".", "")
        return f"data:image/{ext};base64,{encoded_string}"

def generate_html(slides_data, output_path):
    slides_html = ""
    
    for idx, slide_info in enumerate(slides_data):
        title = slide_info.get("title", f"Slide {idx+1}")
        bullets = slide_info.get("bullets", [])
        image_path = slide_info.get("image_path")
        
        bullets_html = ""
        for b in bullets:
            bullets_html += f"<li class='fragment'>{b}</li>\n"
            
        image_html = ""
        if image_path:
            b64_img = get_image_base64(image_path)
            if b64_img:
                image_html = f"<img src='{b64_img}' style='max-height: 400px; max-width: 400px; object-fit: contain; border-radius: 8px;' />"
        
        slide_html = f"""
        <section>
            <h2>{title}</h2>
            <div style="display: flex; align-items: center; justify-content: space-between; text-align: left;">
                <div style="flex: 1; padding-right: 20px;">
                    <ul>
                        {bullets_html}
                    </ul>
                </div>
                <div style="flex: 1; text-align: right;">
                    {image_html}
                </div>
            </div>
        </section>
        """
        slides_html += slide_html

    html_template = f"""
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <title>Presentation</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/reveal.js/4.5.0/reset.min.css">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/reveal.js/4.5.0/reveal.min.css">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/reveal.js/4.5.0/theme/dracula.min.css" id="theme">
    </head>
    <body>
        <div class="reveal">
            <div class="slides">
                {slides_html}
            </div>
        </div>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/reveal.js/4.5.0/reveal.min.js"></script>
        <script>
            Reveal.initialize({{
                hash: true,
                transition: 'convex',
                controls: true,
                progress: true,
            }});
        </script>
    </body>
    </html>
    """
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_template)
        
    return output_path
