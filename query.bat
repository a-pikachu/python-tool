@echo off
setlocal enabledelayedexpansion
set SKU1=0508182
set SKU2=1504099
set SKU3=1504098
set SKU4=0508495

set STORE1=Marine
set STORE2=Cambie
set STORE3=Grandview
set STORE4=North

echo 1. %SKU1%
echo 2. %SKU2%
echo 3. %SKU3%
echo 4. %SKU4%

set /p choice=Enter SKU choice (1.Car Culture, 2.Pop Culture, 3.F1, 4.Team Transport): 
set skuName=!SKU%choice%!

echo 1. %STORE1%
echo 2. %STORE2%
echo 3. %STORE3%
echo 4. %STORE4%

set /p choice=Enter Store choice (1.Marine, 2. Cambie, 3. Grandview, 4.North Vancouver): 
set storeName=!STORE%choice%!

echo Selected SKU: !skuName!
echo Selected Store: !storeName!

docker exec -i openclaw_postgres psql -U openclaw -d openclaw -c "select * from canadian_tire_inventory where product_sku = '!skuName!' and store_name ilike '%%!storeName!%%' order by recorded_at desc;"
endlocal