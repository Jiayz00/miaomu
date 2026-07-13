<?php
namespace app\plugins\nursery\service;

class ScopePolicy
{
    public const WEB_DENIED_CONTROLLERS = [
        'buy',
        'cart',
        'order',
        'orderaftersale',
        'pay',
        'useraddress',
        'usergoodscomments',
        'userintegral',
    ];

    public const API_DENIED_CONTROLLERS = [
        'buy',
        'cart',
        'cashier',
        'order',
        'orderaftersale',
        'ordernotify',
        'paylog',
        'useraddress',
        'usergoodscomments',
        'userintegral',
    ];

    public const ADMIN_DENIED_CONTROLLERS = [
        'express',
        'goodscart',
        'goodscomments',
        'integrallog',
        'order',
        'orderaftersale',
        'payment',
        'paylog',
        'payrequestlog',
        'refundlog',
        'warehouse',
        'warehousegoods',
    ];

    public const WEB_DENIED_ACTIONS = [
        'goods' => ['favor'],
        'usergoodsfavor' => ['cancel', 'delete'],
    ];

    public const API_DENIED_ACTIONS = [
        'goods' => ['favor'],
        'usergoodsfavor' => ['cancel', 'delete'],
    ];

    public const ADMIN_DENIED_ACTIONS = [
        'goods' => ['delete'],
    ];

    public const DENIED_PLUGINS = [
        'agent',
        'aftersale',
        'bargain',
        'cart',
        'coupon',
        'delivery',
        'distribution',
        'finance',
        'groupbuy',
        'integral',
        'inventory',
        'live',
        'memberlevel',
        'membership',
        'merchant',
        'multimerchant',
        'order',
        'payment',
        'points',
        'refund',
        'seckill',
        'supplier',
        'wallet',
    ];

    private const DENIED_PLUGIN_ALIASES = [
        'excellentbuyreturntocash',
        'membershiplevelvip',
        'shop',
        'weixinliveplayer',
    ];

    private const HIDDEN_PLUGIN_ENTRIES = [
        'activity',
        'ask',
        'binding',
        'blog',
        'brand',
        'invoice',
        'realstore',
        'signin',
    ];

    public const WEB_ALLOWED_CONTROLLERS = [
        'index',
        'category',
        'search',
        'goods',
        'user',
        'personal',
        'safety',
        'usergoodsfavor',
        'usergoodsbrowse',
        'message',
        'plugins',
    ];

    public const API_ALLOWED_CONTROLLERS = [
        'index',
        'category',
        'search',
        'goods',
        'user',
        'personal',
        'safety',
        'usergoodsfavor',
        'usergoodsbrowse',
        'message',
        'plugins',
    ];

    public const ADMIN_ALLOWED_CONTROLLERS = [
        'goods',
        'goodscategory',
        'goodsspectemplate',
        'goodsparamstemplate',
        'user',
        'goodsfavor',
        'goodsbrowse',
        'site',
        'navigation',
        'role',
        'power',
    ];

    private const DENIED_ROUTE_MARKERS = [
        'buyindex',
        'cartindex',
        'orderindex',
        'orderaftersaleindex',
        'payindex',
        'useraddressindex',
        'usergoodscommentsindex',
        'userintegralindex',
        'index/buy',
        'index/cart',
        'index/order',
        'index/orderaftersale',
        'index/pay',
        'index/useraddress',
        'index/usergoodscomments',
        'index/userintegral',
        'pages/buy',
        'pages/cart',
        'pages/cart-page',
        'pages/order',
        'pages/pay',
        'pages/paylog-detail',
        'pages/paylog-list',
        'pages/user-cart',
        'pages/user-order',
        'pages/user-order-detail',
        'pages/user-order-history',
        'pages/user-orderaftersale',
        'pages/user-address',
        'pages/user-goods-comments',
        'pages/user-integral',
        's=buy/',
        's=cart/',
        's=order/',
        's=orderaftersale/',
        's=pay/',
        's=useraddress/',
        's=usergoodscomments/',
        's=userintegral/',
    ];

    private const DEFAULT_THEME_VIEW_REPLACEMENTS = [
        'module/goods/grid/base' => '../../../plugins/nursery/view/index/module/goods/grid/base',
        'module/goods/list/base' => '../../../plugins/nursery/view/index/module/goods/list/base',
        'module/goods/slider/binding' => '../../../plugins/nursery/view/index/module/goods/slider/binding',
        'goods/module/middle_base/left/photo_pc_bottom_favor' => '../../../plugins/nursery/view/index/goods/module/middle_base/left/photo_pc_bottom_favor',
    ];

    private const DEFAULT_FALLBACK_VIEW_REPLACEMENTS = [
        '../default/module/goods/grid/base' => '../../../plugins/nursery/view/index/module/goods/grid/base',
        '../default/module/goods/list/base' => '../../../plugins/nursery/view/index/module/goods/list/base',
        '../default/module/goods/slider/binding' => '../../../plugins/nursery/view/index/module/goods/slider/binding',
        '../default/goods/module/middle_base/left/photo_pc_bottom_favor' => '../../../plugins/nursery/view/index/goods/module/middle_base/left/photo_pc_bottom_favor',
    ];

    private const USER_CENTER_ENTRY_VIEWS = [
        '',
        '../default/user/index',
    ];

    public static function IsRequestDenied($module, $controller, $plugins = '')
    {
        $module = self::Normalize($module);
        $controller = self::Normalize($controller);
        if($controller === 'plugins')
        {
            return in_array($module, ['index', 'api', 'admin'], true) && self::IsPluginDenied($plugins);
        }
        if($module === 'index')
        {
            return in_array($controller, self::WEB_DENIED_CONTROLLERS, true);
        }
        if($module === 'api')
        {
            return in_array($controller, self::API_DENIED_CONTROLLERS, true);
        }
        if($module === 'admin')
        {
            return in_array($controller, self::ADMIN_DENIED_CONTROLLERS, true);
        }
        return false;
    }

    public static function IsActionDenied($module, $controller, $action)
    {
        $module = self::Normalize($module);
        $controller = self::Normalize($controller);
        $action = self::Normalize($action);
        if($module === 'index')
        {
            $map = self::WEB_DENIED_ACTIONS;
        } elseif($module === 'api') {
            $map = self::API_DENIED_ACTIONS;
        } elseif($module === 'admin') {
            $map = self::ADMIN_DENIED_ACTIONS;
        } else {
            return false;
        }
        return isset($map[$controller]) && in_array($action, $map[$controller], true);
    }

    public static function IsPluginDenied($plugins)
    {
        $plugins = self::Normalize($plugins);
        return in_array($plugins, self::DENIED_PLUGINS, true) || in_array($plugins, self::DENIED_PLUGIN_ALIASES, true);
    }

    public static function IsPluginEntryDenied($plugins)
    {
        $plugins = self::Normalize($plugins);
        return self::IsPluginDenied($plugins) || in_array($plugins, self::HIDDEN_PLUGIN_ENTRIES, true);
    }

    public static function FilterNavigation($data)
    {
        if(!is_array($data))
        {
            return $data;
        }

        $result = [];
        foreach($data as $key=>$item)
        {
            if(!is_array($item))
            {
                $result[$key] = $item;
                continue;
            }

            $had_children = false;
            foreach(['items', 'item', 'children'] as $children_key)
            {
                if(isset($item[$children_key]) && is_array($item[$children_key]))
                {
                    $had_children = $had_children || !empty($item[$children_key]);
                    $item[$children_key] = self::FilterNavigation($item[$children_key]);
                }
            }

            if(self::IsNavigationItemDenied($item))
            {
                continue;
            }
            if($had_children && self::ChildrenAreEmpty($item) && self::ItemHasNoDestination($item))
            {
                continue;
            }
            $result[$key] = $item;
        }
        return self::PreserveListShape($data, $result);
    }

    public static function FilterAdminMenu($data)
    {
        if(!is_array($data))
        {
            return $data;
        }

        $result = [];
        foreach($data as $key=>$item)
        {
            if(!is_array($item))
            {
                $result[$key] = $item;
                continue;
            }

            $had_items = isset($item['items']) && is_array($item['items']) && !empty($item['items']);
            if(isset($item['items']) && is_array($item['items']))
            {
                $item['items'] = self::FilterAdminMenu($item['items']);
            }

            $control = empty($item['control']) ? '' : self::Normalize($item['control']);
            $action = empty($item['action']) ? '' : self::Normalize($item['action']);
            $url = isset($item['url']) && is_scalar($item['url']) ? (string) $item['url'] : '';
            if(in_array($control, self::ADMIN_DENIED_CONTROLLERS, true) || self::IsActionDenied('admin', $control, $action) || self::UrlContainsDeniedAdminAction($url) || self::IsPluginMenuItemDenied($item))
            {
                continue;
            }
            if($had_items && empty($item['items']) && empty($control) && empty($item['url']))
            {
                continue;
            }
            $result[$key] = $item;
        }
        return self::PreserveListShape($data, $result);
    }

    public static function FilterAdminPower($data)
    {
        if(!is_array($data))
        {
            return $data;
        }

        foreach(array_keys($data) as $key)
        {
            $normalized = self::Normalize($key);
            if($normalized === 'goods_delete')
            {
                unset($data[$key]);
                continue;
            }
            foreach(self::ADMIN_DENIED_CONTROLLERS as $control)
            {
                if(strpos($normalized, $control.'_') === 0)
                {
                    unset($data[$key]);
                    break;
                }
            }
        }
        return $data;
    }

    public static function FilterPluginMap($data)
    {
        if(!is_array($data))
        {
            return $data;
        }

        foreach($data as $key=>$item)
        {
            $plugins = is_array($item) && !empty($item['plugins']) ? $item['plugins'] : $key;
            if(self::IsPluginEntryDenied($plugins))
            {
                unset($data[$key]);
            }
        }
        return $data;
    }

    public static function FilterGoodsButtons($data)
    {
        if(!is_array($data))
        {
            return $data;
        }

        return array_values(array_filter($data, function($item)
        {
            if(!is_array($item))
            {
                return true;
            }
            $type = empty($item['type']) ? '' : self::Normalize($item['type']);
            return !in_array($type, ['buy', 'cart'], true);
        }));
    }

    public static function ReplacementView($view, $theme)
    {
        if(!is_string($view))
        {
            return $view;
        }

        $normalized_view = str_replace('\\', '/', $view);
        if(isset(self::DEFAULT_FALLBACK_VIEW_REPLACEMENTS[$normalized_view]))
        {
            return self::DEFAULT_FALLBACK_VIEW_REPLACEMENTS[$normalized_view];
        }
        if($theme === 'default' && isset(self::DEFAULT_THEME_VIEW_REPLACEMENTS[$normalized_view]))
        {
            return self::DEFAULT_THEME_VIEW_REPLACEMENTS[$normalized_view];
        }
        return $view;
    }

    public static function IsUserCenterEntryView($view)
    {
        if(!is_string($view))
        {
            return false;
        }
        $normalized_view = str_replace('\\', '/', $view);
        return in_array($normalized_view, self::USER_CENTER_ENTRY_VIEWS, true);
    }

    public static function FilterShortcutMenu($data)
    {
        if(!is_array($data))
        {
            return $data;
        }

        $result = [];
        foreach($data as $key=>$item)
        {
            if(!is_array($item))
            {
                $result[$key] = $item;
                continue;
            }

            $menu = isset($item['menu']) && is_scalar($item['menu']) ? self::Normalize($item['menu']) : '';
            $url = isset($item['url']) && is_scalar($item['url']) ? trim((string) $item['url']) : '';
            if(($menu !== '' && $url === '') || (strpos($menu, 'plugins-') === 0 && self::IsPluginEntryDenied(substr($menu, 8))))
            {
                continue;
            }
            if(self::IsNavigationItemDenied($item) || self::UrlContainsDeniedAdminController($url) || self::UrlContainsDeniedAdminAction($url))
            {
                continue;
            }
            $result[$key] = $item;
        }
        return self::PreserveListShape($data, $result);
    }

    private static function IsNavigationItemDenied($item)
    {
        foreach(['control', 'controller'] as $key)
        {
            if(!empty($item[$key]))
            {
                $control = self::Normalize($item[$key]);
                if(in_array($control, self::WEB_DENIED_CONTROLLERS, true) || in_array($control, self::API_DENIED_CONTROLLERS, true))
                {
                    return true;
                }
            }
        }

        if(self::IsPluginMenuItemDenied($item))
        {
            return true;
        }

        foreach(['url', 'value', 'event_value', 'only_tag', 'type'] as $key)
        {
            if(isset($item[$key]) && is_scalar($item[$key]) && self::ContainsDeniedRoute((string) $item[$key]))
            {
                return true;
            }
        }
        return false;
    }

    private static function IsPluginMenuItemDenied($item)
    {
        foreach(['id', 'key'] as $key)
        {
            if(!empty($item[$key]))
            {
                $marker = self::Normalize($item[$key]);
                if(strpos($marker, 'plugins-') === 0 && self::IsPluginEntryDenied(substr($marker, 8)))
                {
                    return true;
                }
            }
        }

        foreach(['url', 'value', 'event_value'] as $key)
        {
            if(!empty($item[$key]) && self::PluginFromUrlIsDenied((string) $item[$key]))
            {
                return true;
            }
        }
        return false;
    }

    private static function PluginFromUrlIsDenied($value)
    {
        $value = self::NormalizeUrl($value);
        foreach([
            '#(?:^|[?&/])pluginsname(?:/|=)([a-z0-9_-]+)#',
            '#(?:^|/)pages/plugins/([a-z0-9_-]+)(?:/|[?#]|$)#',
        ] as $pattern)
        {
            if(preg_match_all($pattern, $value, $matches) > 0)
            {
                foreach($matches[1] as $plugins)
                {
                    if(self::IsPluginEntryDenied($plugins))
                    {
                        return true;
                    }
                }
            }
        }
        return false;
    }

    private static function UrlContainsDeniedAdminController($value)
    {
        $value = self::NormalizeUrl($value);
        foreach(self::ADMIN_DENIED_CONTROLLERS as $controller)
        {
            $controller = preg_quote($controller, '#');
            if(preg_match('#(?:^|[?&])s='.$controller.'/#', $value) === 1 || preg_match('#(?:^|/)admin/'.$controller.'/#', $value) === 1)
            {
                return true;
            }
        }
        return false;
    }

    private static function UrlContainsDeniedAdminAction($value)
    {
        $value = self::NormalizeUrl($value);
        return preg_match('#(?:^|[?&])s=goods/delete(?:[.?#&/]|$)#', $value) === 1 || preg_match('#(?:^|/)admin/goods/delete(?:[.?#&/]|$)#', $value) === 1;
    }

    private static function ContainsDeniedRoute($value)
    {
        $value = self::NormalizeUrl($value);
        if(self::UrlContainsDeniedWebController($value))
        {
            return true;
        }
        foreach(self::DENIED_ROUTE_MARKERS as $marker)
        {
            if(strpos($marker, 's=') === 0)
            {
                if(preg_match('#(?:^|[?&])'.preg_quote($marker, '#').'#', $value) === 1)
                {
                    return true;
                }
            } elseif(strpos($marker, '/') !== false) {
                if(preg_match('#(?:^|[=/])'.preg_quote($marker, '#').'(?=/|[.?#&]|$)#', $value) === 1)
                {
                    return true;
                }
            } elseif(preg_match('#^(?:index)?'.preg_quote($marker, '#').'$#', $value) === 1) {
                return true;
            }
        }
        return false;
    }

    private static function UrlContainsDeniedWebController($value)
    {
        $path = parse_url($value, PHP_URL_PATH);
        if(!is_string($path) || $path === '')
        {
            return false;
        }
        $path = trim($path, '/');
        if($path === '')
        {
            return false;
        }

        $segments = explode('/', $path);
        $controller = $segments[0];
        if($controller === 'index' && isset($segments[1]))
        {
            $controller = $segments[1];
        }
        $controller = explode('.', $controller, 2)[0];
        return in_array(self::Normalize($controller), self::WEB_DENIED_CONTROLLERS, true);
    }

    private static function ChildrenAreEmpty($item)
    {
        foreach(['items', 'item', 'children'] as $key)
        {
            if(isset($item[$key]) && is_array($item[$key]) && !empty($item[$key]))
            {
                return false;
            }
        }
        return true;
    }

    private static function ItemHasNoDestination($item)
    {
        foreach(['url', 'value', 'event_value'] as $key)
        {
            if(!empty($item[$key]))
            {
                return false;
            }
        }
        return true;
    }

    private static function PreserveListShape($source, $result)
    {
        if(empty($source) || array_keys($source) === range(0, count($source)-1))
        {
            return array_values($result);
        }
        return $result;
    }

    private static function NormalizeUrl($value)
    {
        return self::Normalize(rawurldecode(html_entity_decode((string) $value, ENT_QUOTES | ENT_HTML5, 'UTF-8')));
    }

    private static function Normalize($value)
    {
        return strtolower(trim((string) $value));
    }
}
?>
