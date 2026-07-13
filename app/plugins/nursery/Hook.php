<?php
namespace app\plugins\nursery;

use app\plugins\nursery\service\ScopePolicy;
use app\plugins\nursery\service\ReferencePriceService;
use app\plugins\nursery\service\FavoriteService;

class Hook
{
    private const NAVIGATION_HOOKS = [
        'plugins_service_navigation_header_handle',
        'plugins_service_navigation_footer_handle',
        'plugins_service_header_navigation_top_right_handle',
        'plugins_service_quick_navigation_pc',
        'plugins_service_quick_navigation_h5',
        'plugins_service_app_home_navigation_h5',
        'plugins_service_app_user_center_navigation_h5',
        'plugins_service_bottom_navigation_handle',
        'plugins_service_users_center_left_menu_handle',
        'plugins_service_user_center_mini_navigation_handle',
    ];

    public function handle($params = [])
    {
        if(empty($params['hook_name']))
        {
            return null;
        }

        $hook_name = $params['hook_name'];
        if($hook_name === 'plugins_service_system_begin')
        {
            $this->EnforceRequestScope();
        } elseif(in_array($hook_name, self::NAVIGATION_HOOKS, true)) {
            if(isset($params['data']) && is_array($params['data']))
            {
                $params['data'] = ScopePolicy::FilterNavigation($params['data']);
            }
        } elseif($hook_name === 'plugins_service_admin_menu_data') {
            $this->FilterAdminScope($params);
        } elseif($hook_name === 'plugins_service_goods_buy_nav_button_handle') {
            if(isset($params['data']) && is_array($params['data']))
            {
                $had_buttons = !empty($params['data']);
                $params['data'] = ScopePolicy::FilterGoodsButtons($params['data']);
                if($had_buttons && empty($params['data']) && isset($params['error']) && empty($params['error']))
                {
                    $params['error'] = MyLang('goods_only_show_title');
                }
            }
        } elseif($hook_name === 'plugins_service_goods_buy_left_nav_handle') {
            $this->ReplaceFavoriteBuyLeftNav($params);
        } elseif($hook_name === 'plugins_service_goods_list_handle_begin') {
            if(RequestModule() === 'index' && isset($params['params']) && is_array($params['params']))
            {
                $params['params']['is_favor'] = 1;
            }
        } elseif($hook_name === 'plugins_service_goods_save_handle') {
            if(isset($params['params'], $params['data'], $params['spec']) && is_array($params['params']) && is_array($params['data']) && is_array($params['spec']))
            {
                return ReferencePriceService::ValidateSave($params['params'], $params['data'], $params['spec']);
            }
            return DataReturn('苗木价格校验参数不完整', -1);
        } elseif($hook_name === 'plugins_service_goods_save_thing_end') {
            if(isset($params['data']['is_shelves']) && intval($params['data']['is_shelves']) === 1)
            {
                ReferencePriceService::AssertPublishedGoods(isset($params['goods_id']) ? intval($params['goods_id']) : 0);
            }
        } elseif($hook_name === 'plugins_service_goods_field_status_update') {
            if(isset($params['field'], $params['status']) && $params['field'] === 'is_shelves' && intval($params['status']) === 1)
            {
                ReferencePriceService::AssertPublishedGoods(isset($params['goods_id']) ? intval($params['goods_id']) : 0);
            }
        } elseif($hook_name === 'plugins_service_goods_handle_begin') {
            if(isset($params['goods']) && is_array($params['goods']))
            {
                ReferencePriceService::ApplyDisplay($params['goods']);
            }
        } elseif($hook_name === 'plugins_view_goods_detail_panel_price_bottom') {
            return ReferencePriceService::DisclaimerHtml();
        } elseif($hook_name === 'plugins_view_assign_data') {
            $this->FilterAssignedViewData($params);
            $this->AssignFavoriteViewData($params);
        } elseif($hook_name === 'plugins_view_fetch_begin') {
            $this->ReplaceRestrictedView($params);
        }
        return null;
    }

    private function EnforceRequestScope()
    {
        $module = RequestModule();
        $controller = RequestController();
        $action = RequestAction();
        $plugins = (strtolower($controller) === 'plugins') ? PluginsRequestName() : '';
        if(ScopePolicy::IsRequestDenied($module, $controller, $plugins) || ScopePolicy::IsActionDenied($module, $controller, $action))
        {
            abort(404, '该功能在苗木展示站不可用');
        }
    }

    private function FilterAdminScope($params)
    {
        if(isset($params['admin_left_menu']) && is_array($params['admin_left_menu']))
        {
            $params['admin_left_menu'] = ScopePolicy::FilterAdminMenu($params['admin_left_menu']);
        }
        if(isset($params['admin_power']) && is_array($params['admin_power']))
        {
            $params['admin_power'] = ScopePolicy::FilterAdminPower($params['admin_power']);
        }
        if(isset($params['admin_plugins']) && is_array($params['admin_plugins']))
        {
            $params['admin_plugins'] = ScopePolicy::FilterPluginMap($params['admin_plugins']);
        }
        if(isset($params['admin_all_plugins']) && is_array($params['admin_all_plugins']))
        {
            $params['admin_all_plugins'] = ScopePolicy::FilterPluginMap($params['admin_all_plugins']);
        }
    }

    private function FilterAssignedViewData($params)
    {
        if(!isset($params['data']) || !is_array($params['data']))
        {
            return;
        }

        $module = strtolower(RequestModule());
        $controller = strtolower(RequestController());
        $action = strtolower(RequestAction());
        if($module === 'index' && $controller === 'index' && $action === 'index')
        {
            unset($params['data']['user_order_status']);
        } elseif($module === 'admin' && $controller === 'index' && $action === 'init' && isset($params['data']['shortcut_menu_data']) && is_array($params['data']['shortcut_menu_data'])) {
            $params['data']['shortcut_menu_data'] = ScopePolicy::FilterShortcutMenu($params['data']['shortcut_menu_data']);
        }
    }

    private function AssignFavoriteViewData($params)
    {
        if(RequestModule() !== 'index' || !isset($params['data']) || !is_array($params['data']))
        {
            return;
        }
        $params['data']['nursery_favorite_csrf'] = FavoriteService::WebCsrfToken();
        $params['data']['nursery_favorite_add_url'] = PluginsHomeUrl('nursery', 'favorite', 'add');
        $params['data']['nursery_favorite_cancel_url'] = PluginsHomeUrl('nursery', 'favorite', 'cancel');
        $params['data']['nursery_favorite_list_url'] = PluginsHomeUrl('nursery', 'favorite', 'index');
    }

    private function ReplaceFavoriteBuyLeftNav($params)
    {
        if(!isset($params['data']) || !is_array($params['data']))
        {
            return;
        }
        foreach($params['data'] as &$item)
        {
            if(!is_array($item) || ($item['type'] ?? '') !== 'favor')
            {
                continue;
            }
            $active = !empty($item['active']);
            $item['type'] = 'nursery-favorite';
            $item['class'] = trim(($item['class'] ?? '').' nursery-favorite-action');
            $item['document'] = 'data-favorite-status="'.($active ? '1' : '0').'" data-csrf-token="'.htmlspecialchars(FavoriteService::WebCsrfToken(), ENT_QUOTES, 'UTF-8').'" data-add-url="'.htmlspecialchars(PluginsHomeUrl('nursery', 'favorite', 'add'), ENT_QUOTES, 'UTF-8').'" data-cancel-url="'.htmlspecialchars(PluginsHomeUrl('nursery', 'favorite', 'cancel'), ENT_QUOTES, 'UTF-8').'"';
        }
        unset($item);
    }

    private function ReplaceRestrictedView($params)
    {
        if(RequestModule() !== 'index' || !array_key_exists('view', $params))
        {
            return;
        }
        if(RequestController() === 'user' && RequestAction() === 'index' && ScopePolicy::IsUserCenterEntryView($params['view']))
        {
            $params['view'] = '../../../plugins/nursery/view/index/user/index';
            return;
        }
        $params['view'] = ScopePolicy::ReplacementView($params['view'], DefaultTheme());
    }
}
?>
