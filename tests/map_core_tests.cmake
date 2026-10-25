find_package(Qt5 REQUIRED COMPONENTS Widgets Positioning)
# Test-only alias: upstream test harness names Qt6 but its event loop uses QtCore APIs supported by Qt5.
add_library(Qt6::Widgets ALIAS Qt5::Widgets)
set(support_dir "${OMIM_ROOT}/libs/platform/platform_tests_support")
add_library(platform_tests_support STATIC
  "${support_dir}/helpers.cpp" "${support_dir}/scoped_dir.cpp"
  "${support_dir}/scoped_file.cpp" "${support_dir}/scoped_mwm.cpp"
  "${support_dir}/test_socket.cpp" "${support_dir}/writable_dir_changer.cpp")
target_include_directories(platform_tests_support PRIVATE ${OMIM_INCLUDE_DIRS})
target_link_libraries(platform_tests_support PUBLIC platform indexer)
omim_add_test_target(sailplay_core_async "libs/routing/routing_tests/async_router_test.cpp;libs/routing/routing_tests/tools.cpp" FALSE FALSE FALSE FALSE)
target_link_libraries(sailplay_core_async PRIVATE platform_tests_support routing storage)
omim_add_test_target(sailplay_core_blake3 "libs/coding/coding_tests/blake3_test.cpp" FALSE FALSE FALSE FALSE)
target_link_libraries(sailplay_core_blake3 PRIVATE platform_tests_support coding)
omim_add_test_target(sailplay_core_storage "libs/storage/storage_tests/storage_download_tests.cpp;libs/storage/storage_tests/test_map_files_downloader.cpp" FALSE TRUE FALSE FALSE)
target_link_libraries(sailplay_core_storage PRIVATE platform_tests_support storage)
omim_add_test_target(sailplay_core_routes "libs/map/map_tests/routing_manager_tests.cpp" FALSE TRUE FALSE FALSE)
target_link_libraries(sailplay_core_routes PRIVATE platform_tests_support map)

add_executable(sailplay_core_location ${CMAKE_CURRENT_LIST_DIR}/map_location_lifecycle_probe.cpp)
target_include_directories(sailplay_core_location PRIVATE ${OMIM_INCLUDE_DIRS})
target_link_libraries(sailplay_core_location PRIVATE location_service platform Qt5::Positioning Qt5::Core)
