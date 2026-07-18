<?php
namespace app\plugins\nursery\service;

/** Small presentation adapter for dense nursery cards. */
class GoodsDisplayService
{
    public static function DecorateGoods(&$goods)
    {
        if(!is_array($goods))
        {
            return;
        }
        $text = self::SpecificationText($goods['specifications'] ?? []);
        if($text === '' && !empty($goods['spec_desc']))
        {
            $text = trim((string) $goods['spec_desc']);
        }
        $goods['primary_spec_text'] = $text;
        $goods['produce_region_name'] = isset($goods['produce_region_name']) ? trim((string) $goods['produce_region_name']) : '';
    }

    public static function SpecificationText($specifications)
    {
        if(!is_array($specifications))
        {
            return '';
        }
        $choose = $specifications['choose'] ?? [];
        if(!is_array($choose))
        {
            return '';
        }
        $parts = [];
        foreach($choose as $dimension)
        {
            if(count($parts) >= 2 || !is_array($dimension))
            {
                break;
            }
            $name = trim((string) ($dimension['name'] ?? ''));
            $values = $dimension['value'] ?? [];
            $value = (is_array($values) && !empty($values[0]) && is_array($values[0])) ? trim((string) ($values[0]['name'] ?? '')) : '';
            if($name !== '' && $value !== '')
            {
                $parts[] = $name.'：'.$value;
            }
        }
        return implode(' · ', $parts);
    }
}
?>
