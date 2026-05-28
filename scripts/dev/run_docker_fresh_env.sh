#!/bin/bash
# 测试 Docker 在全新环境中的运行

echo "=========================================="
echo "Testing Docker in Fresh Environment"
echo "=========================================="
echo ""

# 定义测试目录
TEST_DIR="/data/ECoG-foundation-model/mnndl_temp/docker_test_brain_researcher"

# 创建测试环境
echo "1. Creating fresh test environment..."
rm -rf $TEST_DIR
mkdir -p $TEST_DIR

# 复制项目文件
echo "2. Copying project files..."
cd /data/ECoG-foundation-model/mnndl_temp/brain_researcher
tar cf - . | (cd $TEST_DIR && tar xf -)
cd $TEST_DIR
ls -la | head -10  # 显示复制的文件

cd $TEST_DIR

# 确保没有 Python 环境
echo "3. Verifying no local Python environment..."
echo "   Current conda env: ${CONDA_DEFAULT_ENV:-none}"
echo "   br command: $(which br 2>&1 || echo 'not found')"
echo "   brain-researcher command: $(which brain-researcher 2>&1 || echo 'not found')"
echo ""

# 检查 Docker
echo "4. Checking Docker installation..."
docker --version
docker-compose --version
echo ""

# 构建 Docker 镜像
echo "5. Building Docker images..."
docker-compose build
echo ""

# 启动服务
echo "6. Starting services..."
docker-compose up -d
echo ""

# 等待服务启动
echo "7. Waiting for services to start..."
sleep 10

# 检查服务状态
echo "8. Checking service status..."
docker-compose ps
echo ""

# 测试 API 健康检查
echo "9. Testing API health endpoints..."
echo -n "BR-KG API (5000): "
curl -s http://localhost:5000/health || echo "Failed"
echo ""
echo -n "Agent API (8000): "
curl -s http://localhost:8000/health || echo "Failed"
echo ""

# 测试 CLI 命令
echo "10. Testing CLI commands in container..."
echo "Testing 'br version':"
docker-compose -f docker-compose.dev.yml run --rm cli version
echo ""

echo "Testing 'br db status':"
docker-compose -f docker-compose.dev.yml run --rm cli db status
echo ""

echo "Testing 'br query stats':"
docker-compose -f docker-compose.dev.yml run --rm cli query stats
echo ""

# 清理
echo "11. Cleaning up..."
docker-compose down
echo ""

echo "=========================================="
echo "Test Complete!"
echo "=========================================="
echo ""
echo "To remove test directory, run:"
echo "rm -rf $TEST_DIR"
