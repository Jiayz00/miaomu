<?php
namespace app\plugins\nursery\service;

use think\facade\Db;
use app\service\GoodsService;

class ReferencePriceService
{
    public const PRICE_PATTERN = '/^[0-9]{1,8}(\.[0-9]{1,2})?$/D';
    public const MAX_PRICE_CENTS = 9999999999;
    public const DISCLAIMER = '页面所示价格为参考价格，实际交易条件可能因规格、数量、库存、运输距离、装卸方式、栽植服务及市场变化而调整，最终以双方确认结果为准。';

    public static function ValidateSave(&$params, &$data, &$spec)
    {
        $catalog_error = CatalogPolicy::ValidateSave($params, $spec);
        if($catalog_error !== null)
        {
            return DataReturn($catalog_error, -1);
        }
        $data['inventory_unit'] = $params['inventory_unit'];
        if(!isset($params['specifications_price']) || !is_array($params['specifications_price']) || empty($params['specifications_price']))
        {
            return DataReturn('苗木商品至少需要一条规格参考价格', -1);
        }
        if(empty($spec['data']) || !is_array($spec['data']) || count($params['specifications_price']) !== count($spec['data']))
        {
            return DataReturn('规格参考价格与规格行数量不一致', -1);
        }

        $is_shelves = isset($data['is_shelves']) && intval($data['is_shelves']) === 1;
        $base_fields = GoodsService::GoodsSpecBaseFields();
        $base_count = count($base_fields);
        $price_offset = array_search('price', $base_fields, true);
        if($price_offset === false)
        {
            return DataReturn('无法定位 ShopXO 规格价格字段', -1);
        }

        foreach($params['specifications_price'] as $index=>$raw_price)
        {
            $normalized = self::NormalizeInputPrice($raw_price);
            if($normalized === null)
            {
                return DataReturn('规格参考价格必须是 0 至 99999999.99 的 ASCII 十进制数，最多两位小数', -1);
            }
            $cents = self::StoredPriceToCents($normalized);
            if($cents === null || $cents > self::MAX_PRICE_CENTS || ($is_shelves && $cents < 1))
            {
                return DataReturn($is_shelves ? '上架商品每条规格参考价格必须在 0.01 至 99999999.99 之间' : '草稿规格参考价格必须在 0.00 至 99999999.99 之间', -1);
            }
            if(!isset($spec['data'][$index]) || !is_array($spec['data'][$index]))
            {
                return DataReturn('规格参考价格对应行不存在', -1);
            }
            $base_start = count($spec['data'][$index])-$base_count;
            if($base_start < 0 || !array_key_exists($base_start+$price_offset, $spec['data'][$index]))
            {
                return DataReturn('规格参考价格结构与固定 ShopXO 基线不一致', -1);
            }
            $params['specifications_price'][$index] = $normalized;
            $spec['data'][$index][$base_start+$price_offset] = $normalized;
        }
        return DataReturn('success', 0);
    }

    public static function AssertPublishedGoods($goods_id)
    {
        $goods = Db::name('Goods')->where(['id'=>intval($goods_id)])->field('id,inventory_unit,min_price,max_price,price')->find();
        if(empty($goods))
        {
            throw new \RuntimeException('商品不存在');
        }
        $catalog_error = CatalogPolicy::PublishedGoodsError($goods_id, $goods['inventory_unit']);
        if($catalog_error !== null)
        {
            throw new \RuntimeException($catalog_error);
        }
        $prices = Db::name('GoodsSpecBase')->where(['goods_id'=>intval($goods_id)])->column('price');
        if(empty($prices))
        {
            throw new \RuntimeException('上架商品至少需要一条规格参考价格');
        }
        $cents = [];
        foreach($prices as $price)
        {
            $value = self::StoredPriceToCents($price);
            if($value === null || $value < 1 || $value > self::MAX_PRICE_CENTS)
            {
                throw new \RuntimeException('上架商品存在无效规格参考价格');
            }
            $cents[] = $value;
        }

        $min = min($cents);
        $max = max($cents);
        $min_price = self::StoredPriceToCents($goods['min_price']);
        $max_price = self::StoredPriceToCents($goods['max_price']);
        $expected_price = self::FormatCents($min).(($min === $max) ? '' : '-'.self::FormatCents($max));
        if($min_price !== $min || $max_price !== $max || (string) $goods['price'] !== $expected_price)
        {
            throw new \RuntimeException('商品参考价汇总与规格价格不一致，请重新保存商品');
        }
    }

    public static function ApplyDisplay(&$goods)
    {
        if(!is_array($goods) || !array_key_exists('min_price', $goods) || !array_key_exists('max_price', $goods))
        {
            return;
        }
        $min = self::StoredPriceToCents($goods['min_price']);
        $max = self::StoredPriceToCents($goods['max_price']);
        if($min === null || $max === null || $min < 1 || $max < $min)
        {
            return;
        }
        $mode = ($min === $max) ? 'fixed' : 'range';
        $symbol = isset($goods['show_price_symbol']) ? (string) $goods['show_price_symbol'] : '';
        $unit_value = isset($goods['inventory_unit']) ? trim((string) $goods['inventory_unit']) : '';
        $unit = ($unit_value === '') ? '' : ' / '.$unit_value;
        $min_text = self::FormatCents($min);
        $max_text = self::FormatCents($max);
        $short_text = $symbol.$min_text.(($mode === 'range') ? ' 起' : '').$unit;
        $text = ($mode === 'fixed') ? $symbol.$min_text.$unit : $symbol.$min_text.' - '.$symbol.$max_text.$unit;

        $goods['show_field_price_status'] = 1;
        $goods['show_field_price_text'] = '参考价';
        $goods['show_price_unit'] = $unit;
        $goods['reference_price'] = [
            'mode'       => $mode,
            'min'        => $min_text,
            'max'        => $max_text,
            'unit'       => $unit_value,
            'currency'   => $symbol,
            'short_text' => $short_text,
            'text'       => $text,
            'disclaimer' => self::DISCLAIMER,
        ];
    }

    public static function DisclaimerHtml()
    {
        return '<div class="nursery-reference-price-disclaimer am-alert am-alert-secondary am-margin-top-sm" role="note">'.self::DISCLAIMER.'</div>';
    }

    public static function NormalizeInputPrice($value)
    {
        if(!is_string($value) || preg_match(self::PRICE_PATTERN, $value) !== 1)
        {
            return null;
        }
        $cents = self::StoredPriceToCents($value);
        return ($cents === null || $cents > self::MAX_PRICE_CENTS) ? null : self::FormatCents($cents);
    }

    public static function StoredPriceToCents($value)
    {
        if(!is_string($value) && !is_int($value))
        {
            return null;
        }
        $value = (string) $value;
        if(preg_match(self::PRICE_PATTERN, $value) !== 1)
        {
            return null;
        }
        if(preg_match('/^([0-9]{1,8})(?:\.([0-9]{1,2}))?$/D', $value, $matches) !== 1)
        {
            return null;
        }
        $fraction = isset($matches[2]) ? str_pad($matches[2], 2, '0', STR_PAD_RIGHT) : '00';
        return intval($matches[1])*100+intval($fraction);
    }

    public static function FormatCents($cents)
    {
        return intdiv(intval($cents), 100).'.'.str_pad((string) (intval($cents)%100), 2, '0', STR_PAD_LEFT);
    }
}
?>
