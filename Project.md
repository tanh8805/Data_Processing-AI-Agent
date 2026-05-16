# AI-Powered CSV Data Processing Pipeline

## 1. Project Overview

### 1.1 Tên dự án

**AI-Powered CSV Data Processing Pipeline**

### 1.2 Mục tiêu dự án

Dự án xây dựng một hệ thống cho phép người dùng upload file CSV thông qua giao diện web. Sau khi upload, hệ thống tự động tiền xử lý dữ liệu theo workflow được thiết kế bằng **LangGraph**.

Kết quả cuối cùng:

- File CSV đã được làm sạch để người dùng tải về.
- Dữ liệu sạch được lưu vào PostgreSQL.
- Các dòng dữ liệu lỗi được lưu thành error report.
- Người dùng có thể theo dõi trạng thái xử lý theo từng bước.

### 1.3 Tech Stack

| Thành phần         | Công nghệ        |
| ------------------ | ---------------- |
| Backend            | Java Spring Boot |
| Frontend           | Web UI           |
| Database           | PostgreSQL       |
| Message Queue      | RabbitMQ         |
| Cache / Job Status | Redis            |
| AI Workflow        | LangGraph        |
| Containerization   | Docker           |
| CI/CD              | GitHub Actions   |
| Optional           | RAG              |

---

## 2. Problem Statement

Trong thực tế, dữ liệu CSV thường bị lỗi trước khi đưa vào hệ thống phân tích hoặc lưu trữ.

Một số lỗi phổ biến:

- Thiếu dữ liệu ở một số cột.
- Dữ liệu bị duplicate.
- Format ngày tháng không đồng nhất.
- Email, số điện thoại, số tiền, mã sản phẩm bị sai định dạng.
- Dữ liệu có khoảng trắng thừa.
- Tên cột không đồng nhất.
- Một số dòng bị lỗi nhưng người dùng không biết lỗi nằm ở đâu.

Vì vậy, hệ thống cần một pipeline để tự động:

1. Nhận file CSV.
2. Kiểm tra dữ liệu.
3. Làm sạch dữ liệu.
4. Chuẩn hóa dữ liệu.
5. Loại bỏ duplicate.
6. Tách dòng hợp lệ và dòng lỗi.
7. Trả về file CSV sạch cho người dùng.
8. Lưu dữ liệu sạch vào database.

---

## 3. Goals & Non-goals

### 3.1 Goals

- Cho phép người dùng upload file CSV.
- Xử lý file theo background job.
- Hiển thị trạng thái xử lý realtime hoặc gần realtime.
- Dùng LangGraph để thiết kế workflow tiền xử lý dữ liệu.
- Trả về file CSV đã được xử lý.
- Tạo error report cho các dòng lỗi.
- Lưu cleaned data vào PostgreSQL.
- Dùng RabbitMQ để tách quá trình xử lý file khỏi request chính.
- Dùng Redis để lưu trạng thái job.
- Có Docker để dễ chạy local.
- Có CI/CD cơ bản để phục vụ portfolio/CV.

### 3.2 Non-goals

Version đầu tiên chưa tập trung vào:

- Xử lý Excel, JSON hoặc API data.
- Cho người dùng map cột thủ công.
- Xử lý dữ liệu cực lớn hàng triệu dòng.
- Realtime streaming từng dòng dữ liệu.
- Multi-tenant phức tạp.
- Authentication nâng cao.
- Phân quyền admin/user chi tiết.
- RAG bắt buộc.

---

## 4. Main Use Case

### 4.1 Người dùng chính

Người dùng là người muốn tiền xử lý dữ liệu từ file CSV nhưng không muốn tự viết script thủ công.

Ví dụ:

- Data analyst.
- Backend developer.
- Sinh viên làm project dữ liệu.
- Người cần làm sạch dữ liệu trước khi import vào hệ thống.
- Người cần chuẩn hóa file CSV trước khi phân tích.

### 4.2 Use case chính

Người dùng upload một file CSV bất kỳ. Hệ thống xử lý file và trả về:

- File CSV sạch.
- Báo cáo lỗi.
- Trạng thái xử lý.
- Kết quả lưu dữ liệu sạch vào PostgreSQL.

---

## 5. User Flow

```text
User
  ↓
Upload CSV file
  ↓
Backend nhận file
  ↓
Tạo processing job
  ↓
Đẩy job vào RabbitMQ
  ↓
Worker nhận job
  ↓
LangGraph chạy workflow xử lý dữ liệu
  ↓
Validate dữ liệu
  ↓
Clean dữ liệu
  ↓
Normalize dữ liệu
  ↓
Remove duplicates
  ↓
Tách valid rows và invalid rows
  ↓
Lưu cleaned data vào PostgreSQL
  ↓
Tạo cleaned CSV file
  ↓
Tạo error report file
  ↓
Cập nhật trạng thái job vào Redis
  ↓
User tải file kết quả
```

---

## 6. System Architecture

### 6.1 High-level Architecture

```text
┌──────────────────┐
│      Web UI      │
│  Upload CSV      │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Spring Boot API  │
│ Upload Service   │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│    RabbitMQ      │
│ Processing Queue │
└────────┬─────────┘
         │
         ▼
┌─────────────────────────┐
│ Data Processing Worker  │
│ LangGraph Workflow      │
└───────┬─────────┬───────┘
        │         │
        ▼         ▼
┌────────────┐  ┌────────────┐
│ PostgreSQL │  │   Redis    │
│ Clean Data │  │ Job Status │
└────────────┘  └────────────┘
        │
        ▼
┌─────────────────────┐
│ File Storage Local  │
│ Cleaned CSV / Error │
└─────────────────────┘
```

---

## 7. Technology Stack Explanation

### 7.1 Java Spring Boot

Spring Boot dùng để xây dựng backend chính.

Nhiệm vụ:

- Nhận file upload từ người dùng.
- Validate file đầu vào.
- Tạo job xử lý.
- Gửi job vào RabbitMQ.
- Cung cấp API lấy trạng thái job.
- Cung cấp API tải file kết quả.
- Quản lý metadata của job.
- Kết nối PostgreSQL, Redis, RabbitMQ.

### 7.2 RabbitMQ

RabbitMQ dùng để xử lý bất đồng bộ.

Thay vì xử lý file ngay trong request upload, backend sẽ:

- Nhận file.
- Lưu file tạm.
- Tạo job.
- Đẩy job vào queue.
- Trả response ngay cho người dùng.

Worker sẽ nhận job từ RabbitMQ và xử lý sau.

Lợi ích:

- Không làm request upload bị timeout.
- Có thể retry khi xử lý lỗi.
- Có thể scale nhiều worker.
- Tách biệt upload service và processing service.

### 7.3 Redis

Redis dùng để lưu trạng thái xử lý job.

Ví dụ trạng thái:

- `UPLOADED`
- `QUEUED`
- `PROCESSING`
- `VALIDATING`
- `CLEANING`
- `NORMALIZING`
- `DEDUPLICATING`
- `SAVING_TO_DB`
- `GENERATING_OUTPUT`
- `COMPLETED`
- `FAILED`

Redis phù hợp vì:

- Đọc ghi nhanh.
- Phù hợp lưu trạng thái tạm thời.
- Frontend có thể gọi API liên tục để lấy progress.
- Có thể dùng TTL để tự xóa job status cũ.

### 7.4 PostgreSQL

PostgreSQL dùng để lưu dữ liệu đã được làm sạch.

Version đầu chỉ lưu cleaned data.

Không lưu raw data vào database để giảm độ phức tạp.

### 7.5 LangGraph

LangGraph dùng để thiết kế workflow xử lý dữ liệu dưới dạng graph.

Mỗi bước xử lý là một node.

Ví dụ:

```text
START
  ↓
read_csv
  ↓
validate_schema
  ↓
clean_data
  ↓
normalize_data
  ↓
remove_duplicates
  ↓
split_valid_invalid_rows
  ↓
save_cleaned_data
  ↓
generate_output_files
  ↓
END
```

LangGraph giúp pipeline rõ ràng, dễ mở rộng, dễ debug và thể hiện tốt trong CV.

### 7.6 Docker

Docker dùng để chạy toàn bộ hệ thống local.

Các service chính:

- Spring Boot backend.
- PostgreSQL.
- Redis.
- RabbitMQ.
- AI processing service nếu tách riêng.

### 7.7 CI/CD

CI/CD dùng để tự động kiểm tra project khi push code.

Pipeline cơ bản:

- Checkout source code.
- Build backend.
- Run test.
- Build Docker image.
- Optional: deploy lên server.

---

## 8. Functional Requirements

### 8.1 Upload CSV

Người dùng có thể upload file CSV từ giao diện.

Yêu cầu:

- Chỉ chấp nhận file `.csv`.
- Giới hạn dung lượng file.
- Kiểm tra file có rỗng không.
- Kiểm tra file có header không.
- Sau khi upload thành công, hệ thống trả về `jobId`.

Response ví dụ:

```json
{
  "jobId": "JOB_123456",
  "status": "QUEUED",
  "message": "File uploaded successfully and queued for processing"
}
```

### 8.2 Processing Status

Người dùng có thể xem trạng thái xử lý.

Ví dụ response:

```json
{
  "jobId": "JOB_123456",
  "status": "CLEANING",
  "progress": 45,
  "currentStep": "Cleaning data",
  "totalRows": 1000,
  "processedRows": 450,
  "validRows": 430,
  "invalidRows": 20
}
```

### 8.3 Download Cleaned CSV

Sau khi xử lý xong, người dùng có thể tải file CSV đã được làm sạch.

Điều kiện:

- Job phải ở trạng thái `COMPLETED`.
- File output phải tồn tại.

### 8.4 Download Error Report

Nếu có dòng lỗi, hệ thống tạo error report.

Error report gồm:

| Field           | Ý nghĩa          |
| --------------- | ---------------- |
| `row_number`    | Số dòng bị lỗi   |
| `original_data` | Dữ liệu gốc      |
| `error_reason`  | Lý do lỗi        |
| `failed_column` | Cột bị lỗi       |
| `suggested_fix` | Gợi ý sửa nếu có |

Ví dụ:

```csv
row_number,failed_column,error_reason,suggested_fix
5,email,Invalid email format,Use valid email format
8,created_date,Invalid date format,Use yyyy-MM-dd
```

### 8.5 Save Cleaned Data

Sau khi xử lý xong, dữ liệu hợp lệ sẽ được lưu vào PostgreSQL.

Vì CSV là bất kỳ, thiết kế database nên dùng dạng flexible schema.

Đề xuất lưu cleaned row dưới dạng `JSONB`.

---

## 9. Non-functional Requirements

### 9.1 Performance

- File nhỏ và vừa phải xử lý được trong thời gian hợp lý.
- Version đầu nên hỗ trợ file từ vài trăm đến vài chục nghìn dòng.
- Xử lý file bằng background worker để tránh timeout.

### 9.2 Scalability

Có thể scale bằng cách:

- Tăng số lượng worker.
- Tăng consumer RabbitMQ.
- Tách processing service ra khỏi backend chính.
- Dùng object storage trong tương lai.

### 9.3 Reliability

Hệ thống cần:

- Retry job khi lỗi tạm thời.
- Ghi trạng thái `FAILED` nếu xử lý thất bại.
- Lưu error message rõ ràng.
- Không làm mất file gốc trong quá trình xử lý.

### 9.4 Observability

Nên có log cho các bước:

- Upload file.
- Queue job.
- Start processing.
- Validate.
- Clean.
- Normalize.
- Save DB.
- Generate output.
- Complete / Failed.

---

## 10. Data Processing Pipeline Design

### 10.1 Pipeline Overview

Pipeline xử lý dữ liệu gồm các bước:

1. Read CSV
2. Validate File
3. Detect Columns
4. Clean Data
5. Normalize Data
6. Remove Duplicates
7. Split Valid / Invalid Rows
8. Save Cleaned Data
9. Generate Cleaned CSV
10. Generate Error Report

### 10.2 Step 1: Read CSV

Mục tiêu:

- Đọc file CSV.
- Lấy header.
- Lấy từng dòng dữ liệu.
- Chuyển dữ liệu thành dạng internal object để xử lý.

Input:

- `uploaded_file.csv`

Output:

- `List<RowData>`

### 10.3 Step 2: Validate File

Kiểm tra file có hợp lệ không.

Các rule cơ bản:

- File không được rỗng.
- File phải có header.
- Số cột mỗi dòng phải khớp với header.
- File phải đọc được encoding.
- Không vượt quá dung lượng cho phép.

Nếu file lỗi nghiêm trọng:

- Job status = `FAILED`

Nếu chỉ một số dòng lỗi:

- Tiếp tục xử lý.
- Dòng lỗi đưa vào error report.

### 10.4 Step 3: Detect Columns

Vì người dùng có thể upload bất kỳ CSV nào, hệ thống không bắt buộc map cột.

Hệ thống chỉ detect:

- Danh sách tên cột.
- Kiểu dữ liệu dự đoán của từng cột.
- Số lượng missing value.
- Số lượng duplicate.
- Một số pattern phổ biến.

Ví dụ detect type:

| Input value      | Detected type |
| ---------------- | ------------- |
| `john@gmail.com` | email         |
| `2024-01-01`     | date          |
| `100000`         | number        |
| `Nguyen Van A`   | text          |

### 10.5 Step 4: Clean Data

Các thao tác cleaning cơ bản:

- Trim khoảng trắng đầu/cuối.
- Xóa ký tự không hợp lệ.
- Chuyển chuỗi rỗng thành `null`.
- Chuẩn hóa text.
- Loại bỏ dòng hoàn toàn rỗng.
- Chuẩn hóa tên cột.

Ví dụ:

| Before             | After            |
| ------------------ | ---------------- |
| `" Nguyen Van A "` | `"Nguyen Van A"` |
| `""`               | `null`           |
| `" EMAIL "`        | `"email"`        |

### 10.6 Step 5: Normalize Data

Chuẩn hóa format dữ liệu.

Ví dụ:

| Loại dữ liệu | Chuẩn hóa                             |
| ------------ | ------------------------------------- |
| Email        | lowercase                             |
| Date         | `yyyy-MM-dd`                          |
| Phone        | remove spaces, normalize country code |
| Number       | remove comma, parse numeric           |
| Text         | trim, normalize spacing               |

Ví dụ:

| Before           | After            |
| ---------------- | ---------------- |
| `JOHN@GMAIL.COM` | `john@gmail.com` |
| `01/05/2024`     | `2024-05-01`     |
| `1,000`          | `1000`           |

### 10.7 Step 6: Remove Duplicates

Hệ thống loại bỏ duplicate row.

Cách đơn giản cho version đầu:

- So sánh toàn bộ dòng sau khi đã clean.
- Nếu hai dòng giống nhau hoàn toàn thì giữ dòng đầu tiên.
- Các dòng trùng phía sau bị loại bỏ.

Output:

- Cleaned rows.
- Duplicate rows count.

### 10.8 Step 7: Split Valid / Invalid Rows

Sau khi xử lý, hệ thống tách dữ liệu thành hai nhóm:

- `valid_rows`
- `invalid_rows`

Valid rows:

- Có thể lưu vào PostgreSQL.
- Có thể xuất ra cleaned CSV.

Invalid rows:

- Không lưu vào bảng cleaned data.
- Đưa vào error report.

### 10.9 Step 8: Save Cleaned Data

Dữ liệu hợp lệ được lưu vào PostgreSQL.

Do CSV có cấu trúc bất kỳ, nên dùng `JSONB` để lưu nội dung dòng.

Ví dụ `data`:

```json
{
  "name": "Nguyen Van A",
  "email": "a@gmail.com",
  "age": 22
}
```

### 10.10 Step 9: Generate Cleaned CSV

Tạo file CSV mới từ valid rows.

Tên file đề xuất:

- `cleaned_JOB_123456.csv`

### 10.11 Step 10: Generate Error Report

Nếu có dòng lỗi, tạo file error report.

Tên file đề xuất:

- `error_report_JOB_123456.csv`

---

## 11. LangGraph Workflow Design

### 11.1 Vai trò của LangGraph

LangGraph không chỉ dùng để gọi AI, mà dùng để thiết kế workflow xử lý dữ liệu có trạng thái rõ ràng.

Trong dự án này, LangGraph đóng vai trò là bộ điều phối pipeline.

Mỗi node phụ trách một bước xử lý.

### 11.2 Graph Flow

```text
START
  ↓
read_csv_node
  ↓
validate_file_node
  ↓
detect_columns_node
  ↓
clean_data_node
  ↓
normalize_data_node
  ↓
remove_duplicates_node
  ↓
split_rows_node
  ↓
save_to_database_node
  ↓
generate_output_node
  ↓
END
```

### 11.3 Graph State Design

State là object chứa dữ liệu được truyền qua các node.

Ví dụ state concept:

- `jobId`
- `filePath`
- `headers`
- `rawRows`
- `cleanedRows`
- `invalidRows`
- `duplicateRows`
- `totalRows`
- `processedRows`
- `currentStep`
- `errorMessages`
- `outputFilePath`
- `errorReportPath`

### 11.4 Node Responsibility

| Node                     | Trách nhiệm                    |
| ------------------------ | ------------------------------ |
| `read_csv_node`          | Đọc file CSV                   |
| `validate_file_node`     | Kiểm tra file hợp lệ           |
| `detect_columns_node`    | Phân tích cột                  |
| `clean_data_node`        | Làm sạch dữ liệu               |
| `normalize_data_node`    | Chuẩn hóa dữ liệu              |
| `remove_duplicates_node` | Xóa duplicate                  |
| `split_rows_node`        | Tách valid/invalid rows        |
| `save_to_database_node`  | Lưu cleaned data               |
| `generate_output_node`   | Tạo output CSV và error report |

### 11.5 Conditional Flow

Một số node có thể có điều kiện.

Ví dụ:

- `validate_file_node`
  - valid file → `detect_columns_node`
  - invalid file → `failed_node`

Ví dụ khác:

- `split_rows_node`
  - has valid rows → `save_to_database_node`
  - no valid rows → `generate_error_report_node`

### 11.6 AI Agent Role

Trong version đầu, AI Agent không cần tự động sửa dữ liệu quá phức tạp.

AI Agent nên tập trung vào:

- Phân tích chất lượng dữ liệu.
- Gợi ý rule làm sạch.
- Sinh summary report.
- Đưa ra cảnh báo bất thường.

Ví dụ output của AI Agent:

```text
Data Quality Summary:
- Total rows: 1000
- Valid rows: 920
- Invalid rows: 80
- Duplicate rows removed: 35
- Most common issue: invalid email format
- Suggested improvement: standardize date format before upload
```

---

## 12. RabbitMQ Design

### 12.1 Vai trò RabbitMQ

RabbitMQ dùng để đưa job xử lý CSV vào background.

Backend không xử lý file ngay trong request upload.

Flow:

```text
User upload file
  ↓
Spring Boot lưu file tạm
  ↓
Spring Boot tạo job
  ↓
Spring Boot publish message vào RabbitMQ
  ↓
Worker consume message
  ↓
Worker chạy LangGraph pipeline
```

### 12.2 Queue Design

Queue đề xuất:

- `csv.processing.queue`

Exchange đề xuất:

- `csv.processing.exchange`

Routing key:

- `csv.process`

### 12.3 Message Payload

Message gửi vào RabbitMQ nên chứa metadata, không nên chứa toàn bộ file.

Ví dụ:

```json
{
  "jobId": "JOB_123456",
  "filePath": "/uploads/JOB_123456/input.csv",
  "uploadedBy": "user_001",
  "createdAt": "2026-05-14T10:00:00"
}
```

### 12.4 Retry Strategy

Nếu worker xử lý lỗi:

- Retry tối đa 3 lần.
- Nếu vẫn lỗi, chuyển job sang trạng thái `FAILED`.
- Ghi error message vào Redis/PostgreSQL.

---

## 13. Redis Design

### 13.1 Vai trò Redis

Redis dùng để lưu trạng thái xử lý realtime.

Ví dụ key:

- `job:JOB_123456:status`

Value:

```json
{
  "status": "CLEANING",
  "progress": 45,
  "currentStep": "Cleaning data",
  "totalRows": 1000,
  "processedRows": 450,
  "validRows": 430,
  "invalidRows": 20
}
```

### 13.2 Job Status Lifecycle

```text
UPLOADED
  ↓
QUEUED
  ↓
PROCESSING
  ↓
VALIDATING
  ↓
CLEANING
  ↓
NORMALIZING
  ↓
DEDUPLICATING
  ↓
SAVING_TO_DB
  ↓
GENERATING_OUTPUT
  ↓
COMPLETED

Nếu lỗi:
FAILED
```

### 13.3 Progress Calculation

Progress có thể chia theo bước:

| Step              | Progress |
| ----------------- | -------- |
| Uploaded          | 5%       |
| Queued            | 10%      |
| Validating        | 20%      |
| Cleaning          | 40%      |
| Normalizing       | 55%      |
| Deduplicating     | 70%      |
| Saving to DB      | 85%      |
| Generating output | 95%      |
| Completed         | 100%     |

---

## 14. PostgreSQL Design

### 14.1 Database Purpose

PostgreSQL dùng để lưu:

- Metadata của processing job.
- Cleaned data.
- Thông tin file output.
- Thông tin lỗi tổng quan.

### 14.2 Table: `processing_jobs`

Bảng lưu thông tin job.

| Column               | Type      | Description            |
| -------------------- | --------- | ---------------------- |
| `id`                 | UUID      | Primary key            |
| `original_file_name` | VARCHAR   | Tên file gốc           |
| `stored_file_path`   | TEXT      | Đường dẫn file upload  |
| `status`             | VARCHAR   | Trạng thái job         |
| `total_rows`         | INT       | Tổng số dòng           |
| `valid_rows`         | INT       | Số dòng hợp lệ         |
| `invalid_rows`       | INT       | Số dòng lỗi            |
| `duplicate_rows`     | INT       | Số dòng duplicate      |
| `cleaned_file_path`  | TEXT      | Đường dẫn file cleaned |
| `error_report_path`  | TEXT      | Đường dẫn error report |
| `created_at`         | TIMESTAMP | Thời gian tạo          |
| `updated_at`         | TIMESTAMP | Thời gian cập nhật     |

### 14.3 Table: `cleaned_records`

Bảng lưu dữ liệu sạch (flexible schema bằng `JSONB`).

| Column       | Type      | Description                |
| ------------ | --------- | -------------------------- |
| `id`         | UUID      | Primary key                |
| `job_id`     | UUID      | Liên kết `processing_jobs` |
| `row_index`  | INT       | Số thứ tự dòng             |
| `data`       | JSONB     | Dữ liệu cleaned            |
| `created_at` | TIMESTAMP | Thời gian tạo              |

Ví dụ `data`:

```json
{
  "name": "Nguyen Van A",
  "email": "nguyen@example.com",
  "age": 22
}
```

### 14.4 Table: `error_records`

Bảng lưu thông tin dòng lỗi.

| Column          | Type      | Description                |
| --------------- | --------- | -------------------------- |
| `id`            | UUID      | Primary key                |
| `job_id`        | UUID      | Liên kết `processing_jobs` |
| `row_index`     | INT       | Dòng bị lỗi                |
| `original_data` | JSONB     | Dữ liệu gốc                |
| `failed_column` | VARCHAR   | Cột lỗi                    |
| `error_reason`  | TEXT      | Lý do lỗi                  |
| `suggested_fix` | TEXT      | Gợi ý sửa                  |
| `created_at`    | TIMESTAMP | Thời gian tạo              |

---

## 15. API Design

### 15.1 Upload CSV API

- `POST /api/files/upload`
- `Content-Type: multipart/form-data`

Request:

- `file`: `input.csv`

Response:

```json
{
  "jobId": "JOB_123456",
  "status": "QUEUED",
  "message": "File uploaded successfully"
}
```

### 15.2 Get Job Status API

- `GET /api/jobs/{jobId}/status`

Response:

```json
{
  "jobId": "JOB_123456",
  "status": "CLEANING",
  "progress": 45,
  "currentStep": "Cleaning data",
  "totalRows": 1000,
  "processedRows": 450,
  "validRows": 430,
  "invalidRows": 20
}
```

### 15.3 Download Cleaned CSV API

- `GET /api/jobs/{jobId}/download/cleaned`

Response:

- cleaned csv file

### 15.4 Download Error Report API

- `GET /api/jobs/{jobId}/download/errors`

Response:

- error report csv file

### 15.5 Get Job Summary API

- `GET /api/jobs/{jobId}/summary`

Response:

```json
{
  "jobId": "JOB_123456",
  "fileName": "customers.csv",
  "totalRows": 1000,
  "validRows": 920,
  "invalidRows": 45,
  "duplicateRows": 35,
  "status": "COMPLETED",
  "aiSummary": "The file was processed successfully. Most errors are related to invalid email format."
}
```

---

## 16. UI Design

### 16.1 Page 1: Upload Page

Chức năng:

- Chọn file CSV.
- Hiển thị tên file.
- Button upload.
- Hiển thị lỗi nếu file không hợp lệ.

Layout:

```text
[ Title: CSV Data Processing ]

[ Upload Box ]
Drag and drop CSV file here
or
[ Choose File ]

[ Upload Button ]
```

### 16.2 Page 2: Processing Status Page

Chức năng:

- Hiển thị trạng thái job.
- Hiển thị progress bar.
- Hiển thị số dòng đã xử lý.
- Hiển thị số dòng hợp lệ/lỗi.
- Tự động refresh trạng thái.

Layout:

```text
Job ID: JOB_123456

Status: CLEANING

Progress:
[==============      ] 45%

Total rows: 1000
Valid rows: 430
Invalid rows: 20

Current step:
Cleaning data
```

### 16.3 Page 3: Result Page

Chức năng:

- Hiển thị summary.
- Tải cleaned CSV.
- Tải error report nếu có lỗi.
- Hiển thị AI summary nếu có.

Layout:

```text
Processing Completed

Total rows: 1000
Valid rows: 920
Invalid rows: 45
Duplicate rows removed: 35

[ Download Cleaned CSV ]
[ Download Error Report ]

AI Summary:
Most invalid rows contain incorrect email format.
```

---

## 17. File Design

### 17.1 Folder Structure

```text
storage/
  uploads/
    JOB_123456/
      input.csv

  outputs/
    JOB_123456/
      cleaned.csv
      error_report.csv
```

### 17.2 Cleaned CSV Format

Cleaned CSV giữ lại header sau khi đã chuẩn hóa.

Ví dụ:

```csv
name,email,age
Nguyen Van A,nguyen@example.com,22
Tran Van B,tran@example.com,25
```

### 17.3 Error Report Format

```csv
row_number,failed_column,error_reason,suggested_fix
5,email,Invalid email format,Use valid email format
8,date,Invalid date format,Use yyyy-MM-dd
```

---

## 18. Deployment Design

### 18.1 Docker Services

Các service trong Docker Compose:

- `backend`
- `postgres`
- `redis`
- `rabbitmq`
- `processing-worker`

Nếu version đầu muốn đơn giản hơn, backend và processing-worker có thể nằm chung một Spring Boot app.

Nhưng để đẹp hơn cho CV, nên tách concept:

- Backend API service.
- Worker service.

### 18.2 Local Development Flow

```text
docker compose up -d
  ↓
Start PostgreSQL
  ↓
Start Redis
  ↓
Start RabbitMQ
  ↓
Start Backend
  ↓
Start Worker
```

---

## 19. CI/CD Design

### 19.1 GitHub Actions Pipeline

Pipeline đề xuất:

```text
Push code to GitHub
  ↓
Run build
  ↓
Run unit tests
  ↓
Build Docker image
  ↓
Optional deploy
```

### 19.2 CI Steps

1. Checkout source code
2. Set up JDK
3. Build Spring Boot project
4. Run tests
5. Build Docker image
6. Push image to Docker Hub (optional)

---

## 20. Error Handling Design

### 20.1 File Upload Error

Các lỗi có thể xảy ra:

| Error               | Handling     |
| ------------------- | ------------ |
| File không phải CSV | Trả lỗi ngay |
| File rỗng           | Trả lỗi ngay |
| File quá lớn        | Trả lỗi ngay |
| Không đọc được file | Job `FAILED` |

### 20.2 Processing Error

Nếu lỗi trong quá trình xử lý:

- Cập nhật status `FAILED`.
- Lưu error message.
- Cho phép người dùng xem lý do lỗi.
- Không tạo cleaned CSV nếu job fail hoàn toàn.

### 20.3 Row-level Error

Nếu chỉ một vài dòng lỗi:

- Không fail toàn bộ job.
- Đưa dòng lỗi vào error report.
- Tiếp tục xử lý các dòng còn lại.
- Cleaned CSV chỉ chứa dòng hợp lệ.

---

## 21. Security Considerations

### 21.1 File Validation

Cần kiểm tra:

- Extension phải là `.csv`.
- Content type hợp lệ.
- File size không vượt quá giới hạn.
- Không cho upload file executable.
- Không tin hoàn toàn vào tên file người dùng gửi lên.

### 21.2 Path Security

Không dùng trực tiếp filename của người dùng làm đường dẫn lưu file.

Nên dùng:

- `jobId/input.csv`

Thay vì:

- `../../dangerous.csv`

### 21.3 Data Security

- Không log toàn bộ dữ liệu nhạy cảm.
- Chỉ log metadata.
- File output nên có thời hạn lưu.
- Redis job status nên có TTL.

---

## 22. Optional RAG Design

### 22.1 RAG có cần ở version đầu không?

Không bắt buộc.

Version đầu nên tập trung vào pipeline xử lý CSV.

RAG có thể đưa vào phần future improvement.

### 22.2 RAG dùng để làm gì?

RAG có thể dùng để tra cứu rule xử lý dữ liệu từ tài liệu nội bộ.

Ví dụ:

Người dùng upload CSV khách hàng.

RAG có thể đọc tài liệu rule:

- Email must be lowercase
- Phone must follow Vietnam phone format
- Date must use `yyyy-MM-dd`
- Customer status must be `ACTIVE` hoặc `INACTIVE`

Sau đó AI Agent dùng các rule này để kiểm tra dữ liệu.

### 22.3 Future RAG Flow

```text
User upload CSV
  ↓
Detect data type
  ↓
Retrieve cleaning rules from knowledge base
  ↓
LangGraph applies rules
  ↓
Generate cleaned CSV
```

---

## 23. Development Roadmap

### 23.1 Phase 1: Core Backend

Mục tiêu:

- Tạo Spring Boot project.
- Tạo API upload file.
- Lưu file vào local storage.
- Tạo job ID.
- Lưu job metadata vào PostgreSQL.

Kết quả:

- User upload CSV → nhận `jobId`.

### 23.2 Phase 2: RabbitMQ Worker

Mục tiêu:

- Cấu hình RabbitMQ.
- Backend publish job vào queue.
- Worker consume job.
- Cập nhật trạng thái job.

Kết quả:

- Upload CSV → Job vào queue → Worker nhận job.

### 23.3 Phase 3: Processing Pipeline

Mục tiêu:

- Đọc CSV.
- Validate dữ liệu.
- Clean dữ liệu.
- Normalize dữ liệu.
- Remove duplicate.
- Tách valid/invalid rows.

Kết quả:

- Input CSV → Cleaned rows + Error rows.

### 23.4 Phase 4: LangGraph Workflow

Mục tiêu:

- Chuyển pipeline thành graph.
- Mỗi bước là một node.
- State truyền qua các node.
- Có conditional flow khi lỗi.

Kết quả:

- LangGraph điều phối toàn bộ data processing workflow.

### 23.5 Phase 5: Output Files

Mục tiêu:

- Generate cleaned CSV.
- Generate error report.
- API download file.

Kết quả:

- User tải cleaned CSV và error report.

### 23.6 Phase 6: Redis Progress Tracking

Mục tiêu:

- Lưu trạng thái job vào Redis.
- API lấy progress.
- Frontend hiển thị progress bar.

Kết quả:

- User xem tiến trình xử lý realtime/gần realtime.

### 23.7 Phase 7: UI

Mục tiêu:

- Upload page.
- Processing page.
- Result page.
- Download buttons.

Kết quả:

- User dùng được hệ thống qua giao diện.

### 23.8 Phase 8: Docker & CI/CD

Mục tiêu:

- Dockerize backend.
- Docker Compose cho PostgreSQL, Redis, RabbitMQ.
- GitHub Actions build/test.

Kết quả:

- Project chạy được bằng Docker và có CI/CD cơ bản.

---

## 24. Suggested Project Structure

### 24.1 Backend Structure

```text
src/main/java/com/example/datapipeline/
  config/
    RabbitMQConfig
    RedisConfig
    StorageConfig

  controller/
    FileUploadController
    JobController
    DownloadController

  service/
    FileStorageService
    JobService
    QueueProducerService
    CsvProcessingService
    CsvCleaningService
    CsvValidationService
    OutputFileService

  worker/
    CsvProcessingWorker

  langgraph/
    CsvProcessingGraph
    nodes/
      ReadCsvNode
      ValidateFileNode
      DetectColumnsNode
      CleanDataNode
      NormalizeDataNode
      RemoveDuplicatesNode
      SaveToDatabaseNode
      GenerateOutputNode

  repository/
    ProcessingJobRepository
    CleanedRecordRepository
    ErrorRecordRepository

  entity/
    ProcessingJob
    CleanedRecord
    ErrorRecord

  dto/
    UploadResponse
    JobStatusResponse
    JobSummaryResponse
```

---

## 25. MVP Scope

### Must Have

- Upload CSV.
- Tạo job.
- Đẩy job vào RabbitMQ.
- Worker xử lý job.
- Clean dữ liệu cơ bản.
- Remove duplicate.
- Tạo cleaned CSV.
- Tạo error report.
- Lưu cleaned data vào PostgreSQL.
- Lưu job status vào Redis.
- API download file.
- UI upload và xem trạng thái.

### Should Have

- AI summary report.
- LangGraph workflow rõ ràng.
- Docker Compose.
- GitHub Actions.

### Could Have

- RAG.
- Advanced validation rules.
- User authentication.
- WebSocket realtime progress.
- Preview dữ liệu trước và sau khi clean.

---

## 26. Example Processing Scenario

Input CSV:

```csv
name,email,age
  Nguyen Van A  ,NGUYEN@GMAIL.COM,22
Tran Van B,invalid-email,25
Nguyen Van A,nguyen@gmail.com,22
,empty@gmail.com,30
```

Processing Result:

Cleaned CSV:

```csv
name,email,age
Nguyen Van A,nguyen@gmail.com,22
```

Error Report:

```csv
row_number,failed_column,error_reason,suggested_fix
2,email,Invalid email format,Use valid email format
4,name,Missing required-like field,Provide a valid name
```

Summary:

```text
Total rows: 4
Valid rows: 1
Invalid rows: 2
Duplicate rows removed: 1
```

---

## 27. CV Description

### 27.1 Short Version

Built an AI-powered CSV data processing pipeline using Spring Boot, RabbitMQ, Redis, PostgreSQL, Docker, and LangGraph. The system allows users to upload CSV files, processes data asynchronously, cleans and normalizes records, removes duplicates, stores cleaned data, and returns downloadable cleaned CSV and error reports.

### 27.2 Vietnamese Version

Xây dựng hệ thống tiền xử lý dữ liệu CSV sử dụng Spring Boot, RabbitMQ, Redis, PostgreSQL, Docker và LangGraph. Hệ thống cho phép người dùng upload file CSV, xử lý dữ liệu bất đồng bộ, làm sạch dữ liệu, chuẩn hóa format, loại bỏ duplicate, lưu dữ liệu sạch vào PostgreSQL và trả về file CSV đã xử lý kèm báo cáo lỗi.

### 27.3 Highlight Points for CV

- Designed asynchronous data processing architecture using RabbitMQ.
- Implemented job progress tracking with Redis.
- Built CSV cleaning and validation pipeline.
- Used LangGraph to model data processing workflow as graph-based nodes.
- Stored flexible cleaned records using PostgreSQL JSONB.
- Generated downloadable cleaned CSV and error report.
- Containerized services using Docker.
- Added CI/CD pipeline with GitHub Actions.

---

## 28. Final Architecture Summary

```text
User uploads CSV from Web UI
  ↓
Spring Boot API validates and stores file
  ↓
Job metadata is saved into PostgreSQL
  ↓
Job message is sent to RabbitMQ
  ↓
Processing Worker consumes the job
  ↓
LangGraph runs CSV processing workflow
  ↓
Redis stores job progress
  ↓
Cleaned data is saved into PostgreSQL
  ↓
Cleaned CSV and error report are generated
  ↓
User downloads result files from UI
```

---

## 29. Final Decision

Version đầu tiên nên làm theo hướng:

- Simple but realistic.
- Easy enough to code in 1–2 weeks.
- Clean enough to put in CV.
- Architecture looks like real company project.
- LangGraph is used as the main workflow engine for data processing.
- RabbitMQ handles background processing.
- Redis handles job progress.
- PostgreSQL stores cleaned data and job metadata.

---

## 30. Recommended Implementation Order

1. Setup Spring Boot project
2. Setup PostgreSQL entities
3. Build upload CSV API
4. Save uploaded file locally
5. Create processing job
6. Setup RabbitMQ
7. Send job to queue
8. Create worker consume job
9. Build CSV reading logic
10. Build cleaning logic
11. Build validation/error report logic
12. Save cleaned data to PostgreSQL
13. Generate cleaned CSV
14. Generate error report
15. Setup Redis job status
16. Build status API
17. Build download API
18. Build simple UI
19. Docker Compose
20. GitHub Actions CI/CD
