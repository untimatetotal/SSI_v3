create table if not exists users (
    id serial primary key , 
    username VARCHAR(50) not null UNIQUE ,
    email VARCHAR(255) not null UNIQUE  ,
    password_hash text not null ,
    groq_api_key_encrypted text  not null default '' ,
    created_at TIMESTAMPTZ not null DEFAULT now(), 
    updated_at TIMESTAMPTZ  not null default now() 

);

create  table if not exists screening_sessions (
    id text primary key , 
    user_id INTEGER  not null REFERENCES users(id) on delete  cascade , 
    created_at TIMESTAMPTZ not null , 
    jd_label text , 
    resume_count INTEGER DEFAULT 0,
    ai_mode varchar(20) , --- !!!!! อาจจะต้องเปลียนให้รองรับจำนวน key 
    summary JSONB,
    raw_results JSONB
); 

 ----- candidate  1 row / 1resume
create table if not EXISTS candidates (
    id  serial primary key , 
    session_id text not null REFERENCES screening_sessions(id) on delete cascade , 
    user_id INTEGER  not null  REFERENCES users(id) on delete cascade , 
    name  text , 
    file_name text,
    score numeric(5,2) check (score is null  or score between 0 and 100  ),
    recommendation VARCHAR(20) check (recommendation is null or recommendation in ('ผ่าน','พิจารณาเพิ่มเติม','ไม่ผ่าน')),
    tfidf_score       NUMERIC(5,2),
    keyword_score     NUMERIC(5,2),
    struct_score      NUMERIC(5,2),
    ai_score          NUMERIC(5,2),
    gpa               NUMERIC(3,2) CHECK (gpa IS NULL OR gpa BETWEEN 0 AND 4),
    experience_years  NUMERIC(4,1) CHECK (experience_years IS NULL OR experience_years >= 0),
    jd_label          TEXT,
    created_at        TIMESTAMPTZ  NOT NULL,
    deleted_at        TIMESTAMPTZ 

);

--------------- index ที่รองรับ filter หลายมิติ แบบ JTG
create index if not exists    idx_candidates_score on candidates(score);
CREATE INDEX IF NOT EXISTS idx_candidates_gpa            ON candidates(gpa);
CREATE INDEX IF NOT EXISTS idx_candidates_experience     ON candidates(experience_years);
CREATE INDEX IF NOT EXISTS idx_candidates_recommendation ON candidates(recommendation);


create index if not exists idx_candidates_active
    on candidates(user_id, deleted_at, score DESC )
    where deleted_at is null ;

create index if not exists idx_candidates_jd_label_search   
on candidates using GIN (to_tsvector('simple' , coalesce(jd_label, ''))) ;