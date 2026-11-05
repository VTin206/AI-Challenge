# Cửa hàng demo (dữ liệu giả lập)

Đơn hàng có thể có nhiều dòng sản phẩm. Cột `quantity` là số lượng bán, `unit_price` là đơn giá VND, `status` là trạng thái dòng. Doanh thu chỉ tính các dòng không bị hủy hoặc hoàn trả.

RULE [priority=20]: metric.revenue = quantity * unit_price
RULE [priority=20]: exclude.revenue = status in cancelled, returned
RULE [priority=20]: exclude.quantity = status in cancelled, returned

