// The 4 curated "visual style" reference photos, relocated from
// streamlit_interface/template_photos/ (labels match
// streamlit_interface/components/home.py's original picker exactly).
// Files live in public/template-photos/ — served directly by Next.js.
export interface TemplatePhoto {
  id: string;
  label: string;
  file: string;
}

export const TEMPLATE_PHOTOS: TemplatePhoto[] = [
  { id: "template_1", label: "Mobilat modern", file: "template_1.png" },
  { id: "template_2", label: "Clasic, luxos", file: "template_2.jpg" },
  { id: "template_3", label: "Primitor", file: "template_3.jpg" },
  { id: "template_4", label: "Bloc comunist", file: "template_4.jpg" },
];
