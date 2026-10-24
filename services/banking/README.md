# Banking 模块

service.py实现合成数据、账户/余额/流水、账单分析、收款人、转账、定时承诺、订阅取消、双边账务、幂等和回执核验。执行与Policy重查共享同一写事务。SQLite/SQLAlchemy持久化位于pact/storage.py。
