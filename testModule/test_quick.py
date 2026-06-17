from models import Config, ResumeScreener

# กำหนดค่าทุกอย่างตรงนี้เลย ไม่ต้องกรอก
config = Config(
    required_keywords=["data"],
    bonus_keywords=["machine learning"],
    pass_threshold=50,
    review_threshold=30,
)
print("\n วุฒิการศึกษาขั้นต่ำที่ต้องการ") #ลิสต์ word เพิ่มด้วย 
print("  1 = ปวส./อนุปริญญา")
print("  2 = ปริญญาตรี")
print("  3 = ปริญญาโท")
print("  Enter = ไม่กำหนด")
edu_choice = input(" เลือก").strip()

edu_map = {
      "1": ["ปวส", "อนุปริญญา", "diploma"],
    "2": ["ปริญญาตรี", "bachelor", "วศ.บ", "บธ.บ", "วท.บ"],
    "3": ["ปริญญาโท", "master", "วศ.ม", "บธ.ม", "วท.ม"],
}

screener = ResumeScreener(config=config)

results = screener.screen(
    jd_path=r"C:\SSI_v3\JobSpecFile\JD_Marketing_Officer_EN.pdf",
    resume_paths=[
        r"C:\SSI_v3\resume_Areeya.pdf",
        r"C:\SSI_v3\resume_Nutjaree.pdf",
    ],
)

screener.print_results(results)
screener.save_json(results, "test_quick.json")