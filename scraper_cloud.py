for item in potential_items:
            try:
                raw_text = item.text
                if not raw_text: continue
                
                norm_text = normalize_text(raw_text)
                
                # 匹配关键词：提交、重新提交等
                if any(kw in norm_text.lower() for kw in keywords):
                    if norm_text not in existing_set:
                        
                        # === 精准提取作业链接逻辑开始 ===
                        extracted_assignment_link = ""
                        try:
                            # 找到该条目内所有的链接
                            all_links = item.find_elements(By.TAG_NAME, "a")
                            for l in all_links:
                                href = l.get_attribute("href")
                                if href:
                                    # 过滤掉 user 链接，只保留作业相关链接
                                    # 增加对不同作业类型的支持 (assignment, assessment, discussion)
                                    target_patterns = ["/assignment/", "/assessment/", "/discussion/"]
                                    if any(pattern in href.lower() for pattern in target_patterns):
                                        extracted_assignment_link = href
                                        break # 找到作业链接后立即跳出当前链接循环
                        except Exception as e:
                            print(f"提取链接时出错: {e}")
                        # === 精准提取作业链接逻辑结束 ===
                        
                        # 如果没找到作业链接，我们宁愿留空，也不要填 user 链接
                        print(f"发现新数据: {norm_text[:40]}... | Link: {extracted_assignment_link}")
                        
                        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
                        new_rows.append([current_time, raw_text.replace("\n", " "), extracted_assignment_link])
                        existing_set.add(norm_text)
            except Exception as e:
                continue
