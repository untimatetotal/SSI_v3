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

alter table candidates add column if not exists age integer;
alter table candidates add column if not exists gender varchar(10);
alter table candidates add column if not exists salary_expectation numeric(12,2);
alter table candidates add column if not exists reject_reasons jsonb;

create table if not exists resume_library (
    id serial primary key,
    user_id integer not null references users(id) on delete cascade,
    sha1 char(40) not null,
    folder text,
    file_name text,
    file_mtime double precision,
    text text,
    gpa numeric(3,2),
    experience_years numeric(5,1),
    age integer,
    gender varchar(10),
    salary_expectation numeric(12,2),
    indexed_at timestamptz not null default now(),
    unique (user_id, sha1)
);
create index if not exists idx_resume_library_user on resume_library(user_id);
