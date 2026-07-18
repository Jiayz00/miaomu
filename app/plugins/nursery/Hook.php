<?php
namespace app\plugins\nursery;

use app\plugins\nursery\service\ScopePolicy;
use app\plugins\nursery\service\ReferencePriceService;
use app\plugins\nursery\service\FavoriteService;
use app\plugins\nursery\service\InquiryService;

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
                if($hook_name === 'plugins_service_users_center_left_menu_handle')
                {
                    $this->InjectUserInquiryMenu($params['data']);
                }
                $params['data'] = ScopePolicy::FilterNavigation($params['data']);
            }
        } elseif($hook_name === 'plugins_service_admin_menu_data') {
            $this->FilterAdminScope($params);
        } elseif($hook_name === 'plugins_service_goods_buy_nav_button_handle') {
            if(isset($params['data']) && is_array($params['data']))
            {
                $had_buttons = !empty($params['data']);
                $params['data'] = ScopePolicy::FilterGoodsButtons($params['data']);
                $this->AppendInquiryButton($params);
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
            $this->AssignInquiryViewData($params);
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
        if(ScopePolicy::IsLegacyFavoriteListRoute($module, $controller, $action))
        {
            MyRedirect(PluginsHomeUrl('nursery', 'favorite', 'index'), true);
        }
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
            if($this->CanViewInquiryMenu($params))
            {
                $this->InjectAdminInquiryMenu($params['admin_left_menu']);
            }
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

    private function CanViewInquiryMenu($params)
    {
        $admin = isset($params['admin']) && is_array($params['admin']) ? $params['admin'] : [];
        if(in_array(intval($admin['id'] ?? 0), [1], true) || in_array(intval($admin['role_id'] ?? 0), [1], true))
        {
            return true;
        }
        $plugins = isset($params['admin_plugins']) && is_array($params['admin_plugins']) ? $params['admin_plugins'] : [];
        if(empty($plugins['nursery']) || !is_array($plugins['nursery']))
        {
            return false;
        }
        $power = $plugins['nursery']['power'] ?? [];
        return empty($power) || (is_array($power) && in_array('inquiry-index', $power, true));
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
        $params['data']['nursery_favorite_nonce'] = FavoriteService::WebRequestNonce();
        $params['data']['nursery_favorite_add_url'] = PluginsHomeUrl('nursery', 'favorite', 'add');
        $params['data']['nursery_favorite_cancel_url'] = PluginsHomeUrl('nursery', 'favorite', 'cancel');
        $params['data']['nursery_favorite_list_url'] = PluginsHomeUrl('nursery', 'favorite', 'index');
    }

    private function AssignInquiryViewData($params)
    {
        if(RequestModule() !== 'index' || !isset($params['data']) || !is_array($params['data']))
        {
            return;
        }
        $params['data']['nursery_inquiry_nonce'] = InquiryService::WebRequestNonce();
        $params['data']['nursery_inquiry_form_url'] = PluginsHomeUrl('nursery', 'inquiry', 'form');
        $params['data']['nursery_inquiry_create_url'] = PluginsHomeUrl('nursery', 'inquiry', 'create');
        $params['data']['nursery_inquiry_list_url'] = PluginsHomeUrl('nursery', 'inquiry', 'index');
    }

    private function AppendInquiryButton($params)
    {
        if(RequestModule() !== 'index' || !isset($params['goods']['id']) || intval($params['goods']['id']) <= 0 || intval($params['goods']['is_shelves'] ?? 0) !== 1)
        {
            return;
        }
        $goods_id = intval($params['goods']['id']);
        $params['data'][] = [
            'color' => 'second',
            'type'  => 'url',
            'name'  => '立即询价',
            'title' => '提交苗木采购需求',
            'value' => PluginsHomeUrl('nursery', 'inquiry', 'form', ['goods_id'=>$goods_id]),
            'icon'  => 'am-icon-comment-o',
            'class' => 'nursery-inquiry-entry',
        ];
    }

    private function InjectUserInquiryMenu(&$data)
    {
        if(isset($data['business']['item']) && is_array($data['business']['item']))
        {
            foreach($data['business']['item'] as $item)
            {
                if(is_array($item) && in_array('nurseryinquiryindex', $item['contains'] ?? [], true))
                {
                    return;
                }
            }
            $data['business']['item'][] = [
                'name'      => '我的询价',
                'url'       => PluginsHomeUrl('nursery', 'inquiry', 'index'),
                'contains'  => ['nurseryinquiryindex', 'nurseryinquirydetail'],
                'is_show'   => 1,
                'icon'      => 'iconfont icon-comment',
                'is_system' => 0,
            ];
        }
    }

    private function InjectAdminInquiryMenu(&$data)
    {
        foreach($data as $item)
        {
            if(is_array($item) && ($item['nursery_inquiry_menu'] ?? false) === true)
            {
                return;
            }
        }
        $data['nursery_inquiry'] = [
            'name'               => '苗木询价',
            'url'                => PluginsAdminUrl('nursery', 'inquiry', 'index'),
            'control'            => 'plugins',
            'action'             => 'index',
            'is_show'            => 1,
            'icon'               => 'iconfont icon-comment',
            'is_system'          => 0,
            'nursery_inquiry_menu' => true,
        ];
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
            $item['document'] = 'data-favorite-status="'.($active ? '1' : '0').'" data-request-nonce="'.htmlspecialchars(FavoriteService::WebRequestNonce(), ENT_QUOTES, 'UTF-8').'" data-add-url="'.htmlspecialchars(PluginsHomeUrl('nursery', 'favorite', 'add'), ENT_QUOTES, 'UTF-8').'" data-cancel-url="'.htmlspecialchars(PluginsHomeUrl('nursery', 'favorite', 'cancel'), ENT_QUOTES, 'UTF-8').'"';
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
